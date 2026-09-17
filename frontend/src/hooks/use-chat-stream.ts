import { useCallback, useEffect, useReducer, useRef } from "react"
import { describeError, streamChat } from "@/api/client"
import { chatReducer, isTurnRunning } from "@/lib/chat-turns"
import { randomId } from "@/lib/ids"

export function useChatStream() {
	const [turns, dispatch] = useReducer(chatReducer, [])
	const abort = useRef<AbortController | null>(null)
	const threadId = useRef<string | null>(null)

	const ask = useCallback(async (question: string) => {
		abort.current?.abort()
		const controller = new AbortController()
		abort.current = controller
		dispatch({ type: "ask", id: randomId(), question })
		try {
			const query = { question, thread_id: threadId.current }
			for await (const event of streamChat(query, controller.signal)) {
				if (event.event === "done") threadId.current = event.data.thread_id
				dispatch(event)
			}
			dispatch({ type: "settle" })
		} catch (error) {
			if (controller.signal.aborted) return
			dispatch({ type: "fail", error: describeError(error) })
		}
	}, [])

	const stop = useCallback(() => {
		abort.current?.abort()
		dispatch({ type: "settle" })
	}, [])

	/** Drops the thread and its turns: the next question starts a thread of its own. */
	const newThread = useCallback(() => {
		abort.current?.abort()
		threadId.current = null
		dispatch({ type: "clear" })
	}, [])

	useEffect(() => {
		return () => {
			abort.current?.abort()
		}
	}, [])

	const current = turns.at(-1)
	return {
		turns,
		ask,
		stop,
		newThread,
		isBusy: current !== undefined && isTurnRunning(current),
	}
}
