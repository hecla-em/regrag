import * as Sentry from "@sentry/react"
import { useCallback, useEffect, useReducer, useRef } from "react"
import { ApiError, describeError, streamChat } from "@/api/client"
import {
	activeThread,
	NO_THREADS,
	type ThreadsState,
	threadsReducer,
} from "@/lib/chat-threads"
import { type ChatAction, isTurnRunning } from "@/lib/chat-turns"
import { randomId } from "@/lib/ids"

/** This tab's threads and the one open. A question goes to the open thread, or starts one. */
export function useChatThreads() {
	const [state, dispatch] = useReducer(threadsReducer, NO_THREADS)
	const committed = useRef<ThreadsState>(state)
	const abort = useRef<AbortController | null>(null)
	const runningId = useRef<string | null>(null)

	useEffect(() => {
		committed.current = state
	}, [state])

	const ask = useCallback(async (question: string) => {
		abort.current?.abort()
		const controller = new AbortController()
		abort.current = controller
		const open = activeThread(committed.current)
		const id = open?.id ?? randomId()
		runningId.current = id
		const send = (action: ChatAction) => dispatch({ type: "turn", id, action })
		send({ type: "ask", id: randomId(), question, askedAt: Date.now() })
		try {
			const query = { question, thread_id: open?.threadId ?? null }
			for await (const event of streamChat(query, controller.signal)) {
				send(event)
			}
			send({ type: "settle" })
		} catch (error) {
			if (controller.signal.aborted) return
			// An ApiError is the server's own refusal, which it logged. Anything else broke here.
			if (!(error instanceof ApiError)) Sentry.captureException(error)
			send({ type: "fail", error: describeError(error) })
		}
	}, [])

	const stop = useCallback(() => {
		abort.current?.abort()
		const id = runningId.current
		if (id !== null) dispatch({ type: "turn", id, action: { type: "settle" } })
	}, [])

	const openThread = useCallback((id: string | null) => {
		dispatch({ type: "open", id })
	}, [])

	useEffect(() => {
		return () => {
			abort.current?.abort()
		}
	}, [])

	const thread = activeThread(state)
	const current = thread?.turns.at(-1)
	return {
		threads: state.threads,
		thread,
		ask,
		stop,
		openThread,
		isBusy: current !== undefined && isTurnRunning(current),
	}
}
