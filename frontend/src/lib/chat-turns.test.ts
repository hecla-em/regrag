import { describe, expect, it } from "vitest"
import type { ChatStep } from "@/api/types"
import {
	type ChatAction,
	type ChatTurn,
	chatReducer,
	turnFailure,
} from "./chat-turns"

function asked(): ChatTurn[] {
	return chatReducer([], { type: "ask", id: "t1", question: "q", askedAt: 0 })
}

function run(...actions: ChatAction[]): ChatTurn {
	return actions.reduce(chatReducer, asked())[0]
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

describe("chatReducer", () => {
	it("adds a step to the trail when it starts", () => {
		const turn = run(started("retrieve"))

		expect(turn.steps.map((step) => [step.step, step.status])).toEqual([
			["retrieve", "running"],
		])
	})

	it("settles a running step in place rather than adding it twice", () => {
		const turn = run(started("retrieve"), finished("retrieve", 120))

		expect(turn.steps).toHaveLength(1)
		expect(turn.steps[0]).toMatchObject({ status: "completed", ms: 120 })
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

	it("keeps the trail in the order the run walked it", () => {
		const turn = run(
			started("retrieve"),
			finished("retrieve", 12),
			started("assess"),
			finished("assess", 90),
		)

		expect(turn.steps.map((step) => step.step)).toEqual(["retrieve", "assess"])
	})

	it("counts a started step as the run being under way", () => {
		expect(run(started("retrieve")).status).toBe("streaming")
	})

	it("drops the step that was running when the turn fails", () => {
		const turn = run(
			started("retrieve"),
			finished("retrieve", 12),
			started("assess"),
			{
				event: "error",
				data: { error: "LLMError", message: "boom", request_id: null },
			},
		)

		expect(turn.status).toBe("failed")
		expect(turn.steps.map((step) => step.step)).toEqual(["retrieve"])
	})

	it("drops the step that was running when the reader stops the turn", () => {
		const turn = run(
			started("retrieve"),
			finished("retrieve", 12),
			started("assess"),
			{
				type: "settle",
			},
		)

		expect(turn.status).toBe("settled")
		expect(turn.steps.map((step) => step.step)).toEqual(["retrieve"])
	})

	it("adds a finished step that was never announced as starting", () => {
		const turn = run(finished("retrieve", 12))

		expect(turn.steps).toMatchObject([
			{ step: "retrieve", status: "completed" },
		])
	})

	it("starts a turn with no steps", () => {
		expect(asked()[0].steps).toEqual([])
	})

	it("keeps the error's name beside its message", () => {
		const turn = run({
			event: "error",
			data: { error: "LLMError", message: "boom", request_id: null },
		})

		expect(turn.error).toEqual({ error: "LLMError", message: "boom" })
	})

	it.each([
		["ThreadFullError", "thread_full"],
		["RateLimitedError", "rate_limited"],
		["SpendCapReachedError", "paused"],
		["InternalServerError", "unexpected"],
		["TypeError", "unexpected"],
	] as const)("reads a %s as %s", (error, failure) => {
		const turn = run({ type: "fail", error: { error, message: "detail" } })

		expect(turnFailure(turn)).toBe(failure)
	})

	it("drops a failed turn when a new question is asked", () => {
		const failed = chatReducer(asked(), {
			type: "fail",
			error: { error: "Error", message: "boom" },
		})

		const turns = chatReducer(failed, {
			type: "ask",
			id: "t2",
			question: "q2",
			askedAt: 0,
		})

		expect(turns.map((turn) => turn.id)).toEqual(["t2"])
	})

	it("keeps an answered turn when a new question is asked", () => {
		const answered = chatReducer(asked(), { type: "settle" })

		const turns = chatReducer(answered, {
			type: "ask",
			id: "t2",
			question: "q2",
			askedAt: 0,
		})

		expect(turns.map((turn) => turn.id)).toEqual(["t1", "t2"])
	})
})
