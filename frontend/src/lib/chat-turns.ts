import type {
	ChatErrorResponse,
	ChatSource,
	ChatStep,
	ChatStreamEvent,
	ErrorBody,
} from "@/api/types"

export type ChatTurn = {
	id: string
	question: string
	answer: string
	sources: ChatSource[]
	steps: ChatStep[]
	status: "pending" | "streaming" | "settled" | "failed"
	error: ErrorBody | null
}

/** Whether the run behind a turn is still under way: asked and not yet answering, or answering. */
export function isTurnRunning(turn: ChatTurn): boolean {
	return turn.status === "pending" || turn.status === "streaming"
}

export type TurnFailure =
	| "thread_full"
	| "rate_limited"
	| "paused"
	| "unexpected"

const FAILURES_BY_ERROR: Record<string, TurnFailure> = {
	ThreadFullError: "thread_full",
	RateLimitedError: "rate_limited",
	SpendCapReachedError: "paused",
} satisfies Partial<Record<ChatErrorResponse["error"], TurnFailure>>

/** Why a turn failed, as far as the reader is told: the refusals they can act on, or anything else. */
export function turnFailure(turn: ChatTurn): TurnFailure {
	return FAILURES_BY_ERROR[turn.error?.error ?? ""] ?? "unexpected"
}

export type ChatAction =
	| { type: "ask"; id: string; question: string }
	| { type: "settle" }
	| { type: "fail"; error: ErrorBody }
	| { type: "clear" }
	| ChatStreamEvent

/** The trail with this step in it: a starting step joins the end, and a finished one settles
 * the earliest still running, since the graph finishes steps in the order it started them. */
function recordStep(steps: ChatStep[], step: ChatStep): ChatStep[] {
	if (step.status === "running") return [...steps, step]
	const settling = steps.findIndex((held) => held.status === "running")
	if (settling === -1) return [...steps, step]
	return steps.map((held, index) => (index === settling ? step : held))
}

/** The path a run took once it is over: a step still running when the run ended never ran. */
function finishedSteps(steps: ChatStep[]): ChatStep[] {
	return steps.filter((step) => step.status === "completed")
}

function applyToTurn(turn: ChatTurn, action: ChatAction): ChatTurn {
	if ("event" in action) {
		switch (action.event) {
			case "sources":
				return { ...turn, sources: action.data, status: "streaming" }
			case "step":
				return {
					...turn,
					steps: recordStep(turn.steps, action.data),
					status: "streaming",
				}
			case "text":
				return {
					...turn,
					answer: turn.answer + action.data,
					status: "streaming",
				}
			case "done":
				return turn.status === "failed" ? turn : { ...turn, status: "settled" }
			case "error":
				return {
					...turn,
					steps: finishedSteps(turn.steps),
					status: "failed",
					error: { error: action.data.error, message: action.data.message },
				}
		}
	}
	switch (action.type) {
		case "settle":
			return turn.status === "failed"
				? turn
				: { ...turn, steps: finishedSteps(turn.steps), status: "settled" }
		case "fail":
			return {
				...turn,
				steps: finishedSteps(turn.steps),
				status: "failed",
				error: action.error,
			}
		default:
			return turn
	}
}

/** The turns with a failed last one dropped: a new question replaces it rather than follows it. */
function withoutFailedTurn(turns: ChatTurn[]): ChatTurn[] {
	return turns.at(-1)?.status === "failed" ? turns.slice(0, -1) : turns
}

export function chatReducer(turns: ChatTurn[], action: ChatAction): ChatTurn[] {
	if ("type" in action && action.type === "clear") return []
	if ("type" in action && action.type === "ask") {
		return [
			...withoutFailedTurn(turns),
			{
				id: action.id,
				question: action.question,
				answer: "",
				sources: [],
				steps: [],
				status: "pending",
				error: null,
			},
		]
	}
	const current = turns.at(-1)
	if (current === undefined) return turns
	return [...turns.slice(0, -1), applyToTurn(current, action)]
}
