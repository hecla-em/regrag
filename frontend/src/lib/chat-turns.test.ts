import { expect, it } from "vitest"
import type { ChatStep } from "@/api/types"
import { type ChatAction, type ChatTurn, chatReducer } from "./chat-turns"

function asked(): ChatTurn[] {
	return chatReducer([], { type: "ask", id: "t1", question: "q" }, 0)
}

function run(...actions: ChatAction[]): ChatTurn {
	return actions.reduce(
		(turns, action) => chatReducer(turns, action, 0),
		asked(),
	)[0]
}

function started(
	step: ChatStep["step"],
	subject: string | null = null,
): ChatAction {
	return { event: "step", data: { step, ms: 0, status: "running", subject } }
}

function finished(
	step: ChatStep["step"],
	ms: number,
	subject: string | null = null,
): ChatAction {
	return { event: "step", data: { step, ms, status: "completed", subject } }
}

const failure: ChatAction = {
	event: "error",
	data: { error: "LLMError", message: "boom", request_id: null },
}
const settle: ChatAction = { type: "settle" }
const done: ChatAction = { event: "done", data: { thread_id: "server-1" } }

it.each([
	[
		"adds a step to the trail when it starts",
		[started("retrieve")],
		[["retrieve", "running"]],
	],
	[
		"settles a running step in place rather than adding it twice",
		[started("retrieve"), finished("retrieve", 120)],
		[["retrieve", "completed"]],
	],
	[
		"keeps the trail in the order the run walked it",
		[
			started("retrieve"),
			finished("retrieve", 12),
			started("assess"),
			finished("assess", 90),
		],
		[
			["retrieve", "completed"],
			["assess", "completed"],
		],
	],
	[
		"adds a finished step that was never announced as starting",
		[finished("retrieve", 12)],
		[["retrieve", "completed"]],
	],
])("the step trail %s", (_rule, actions, expected) => {
	const turn = run(...actions)

	expect(turn.steps.map((step) => [step.step, step.status])).toEqual(expected)
})

it("settles concurrent calls in the order they started", () => {
	const turn = run(
		started("tool_search", "penalties"),
		started("tool_search", "verification"),
		finished("tool_search", 500, "penalties"),
	)

	expect(turn.steps.map((step) => [step.subject, step.status])).toEqual([
		["penalties", "completed"],
		["verification", "running"],
	])
})

it.each([
	["fails and drops the step that was running", [failure], "failed"],
	[
		"stopped by the reader drops the step that was running",
		[settle],
		"settled",
	],
	["stays failed when the stream then settles", [failure, settle], "failed"],
	[
		"stays failed when a done frame follows the error",
		[failure, done],
		"failed",
	],
])("a turn that %s", (_rule, ending, status) => {
	const turn = run(
		started("retrieve"),
		finished("retrieve", 12),
		started("assess"),
		...ending,
	)

	expect(turn.status).toBe(status)
	expect(turn.steps.map((step) => step.step)).toEqual(["retrieve"])
})

it.each([
	[
		"drops a failed turn",
		{ type: "fail", error: { error: "Error", message: "boom" } },
		["t2"],
	],
	["keeps an answered turn", settle, ["t1", "t2"]],
] as const)("a new question %s", (_rule, ending, expected) => {
	const turns = chatReducer(
		chatReducer(asked(), ending, 0),
		{ type: "ask", id: "t2", question: "q2" },
		0,
	)

	expect(turns.map((turn) => turn.id)).toEqual(expected)
})
