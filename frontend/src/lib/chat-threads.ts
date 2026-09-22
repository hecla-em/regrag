import { type ChatAction, type ChatTurn, chatReducer } from "./chat-turns"

/** A thread asked in this tab: its turns, and the server's id for it once a run has reported one. */
export type TabThread = {
	id: string
	threadId: string | null
	turns: ChatTurn[]
}

export type ThreadsState = {
	threads: TabThread[]
	activeId: string | null
}

export type ThreadsAction =
	| { type: "open"; id: string | null }
	| { type: "turn"; id: string; action: ChatAction; at: number }

export const NO_THREADS: ThreadsState = { threads: [], activeId: null }

export function activeThread(state: ThreadsState): TabThread | undefined {
	return state.threads.find((thread) => thread.id === state.activeId)
}

function applyToThread(
	thread: TabThread,
	action: ChatAction,
	at: number,
): TabThread {
	const threadId =
		"event" in action && action.event === "done"
			? action.data.thread_id
			: thread.threadId
	return { ...thread, threadId, turns: chatReducer(thread.turns, action, at) }
}

/** Opening `null` shows a blank page, and the first question asked there starts a thread at the
 * top of the list. */
export function threadsReducer(
	state: ThreadsState,
	action: ThreadsAction,
): ThreadsState {
	if (action.type === "open") return { ...state, activeId: action.id }
	const isAsk = "type" in action.action && action.action.type === "ask"
	const exists = state.threads.some((thread) => thread.id === action.id)
	if (!exists && !isAsk) return state
	const threads = exists
		? state.threads
		: [{ id: action.id, threadId: null, turns: [] }, ...state.threads]
	return {
		activeId: isAsk ? action.id : state.activeId,
		threads: threads.map((thread) =>
			thread.id === action.id
				? applyToThread(thread, action.action, action.at)
				: thread,
		),
	}
}
