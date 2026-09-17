import { describe, expect, it } from "vitest"
import {
	activeThread,
	NO_THREADS,
	type ThreadsAction,
	threadsReducer,
} from "./chat-threads"

function ask(id: string, question: string): ThreadsAction {
	return {
		type: "turn",
		id,
		action: { type: "ask", id: `${id}-${question}`, question, askedAt: 0 },
	}
}

function run(...actions: ThreadsAction[]) {
	return actions.reduce(threadsReducer, NO_THREADS)
}

describe("threadsReducer", () => {
	it("starts a thread with the first question and opens it", () => {
		const state = run(ask("a", "q1"))

		expect(state.activeId).toBe("a")
		expect(activeThread(state)?.turns.map((turn) => turn.question)).toEqual([
			"q1",
		])
	})

	it("lists the newest thread first", () => {
		const state = run(
			ask("a", "q1"),
			{ type: "open", id: null },
			ask("b", "q2"),
		)

		expect(state.threads.map((thread) => thread.id)).toEqual(["b", "a"])
	})

	it("adds a follow-up to the thread it was asked in", () => {
		const state = run(ask("a", "q1"), ask("a", "q2"))

		expect(state.threads).toHaveLength(1)
		expect(state.threads[0].turns.map((turn) => turn.question)).toEqual([
			"q1",
			"q2",
		])
	})

	it("keeps the server's thread id from the done event", () => {
		const state = run(ask("a", "q1"), {
			type: "turn",
			id: "a",
			action: { event: "done", data: { thread_id: "server-1" } },
		})

		expect(state.threads[0].threadId).toBe("server-1")
	})

	it("routes stream events to their own thread, not the open one", () => {
		const state = run(
			ask("a", "q1"),
			{ type: "open", id: null },
			{
				type: "turn",
				id: "a",
				action: { event: "text", data: "answer" },
			},
		)

		expect(state.activeId).toBeNull()
		expect(state.threads[0].turns[0].answer).toBe("answer")
	})

	it("ignores events for a thread it does not hold", () => {
		const state = run({
			type: "turn",
			id: "gone",
			action: { event: "text", data: "answer" },
		})

		expect(state).toBe(NO_THREADS)
	})
})
