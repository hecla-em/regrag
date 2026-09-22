import { expect, it } from "vitest"
import { NO_THREADS, type ThreadsAction, threadsReducer } from "./chat-threads"

function ask(id: string, question: string): ThreadsAction {
	return {
		type: "turn",
		id,
		action: { type: "ask", id: `${id}-${question}`, question },
		at: 0,
	}
}

function run(...actions: ThreadsAction[]) {
	return actions.reduce(threadsReducer, NO_THREADS)
}

it("keeps the server's thread id from the done event", () => {
	const state = run(ask("a", "q1"), {
		type: "turn",
		id: "a",
		action: { event: "done", data: { thread_id: "server-1" } },
		at: 0,
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
			at: 0,
		},
	)

	expect(state.activeId).toBeNull()
	expect(state.threads[0].turns[0].answer).toBe("answer")
})
