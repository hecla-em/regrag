import { useCallback, useEffect, useReducer, useRef } from "react"
import { ApiError, streamChat } from "@/api/client"
import { type ChatAction, chatReducer, isTurnRunning } from "@/lib/chat-turns"
import { randomId } from "@/lib/ids"

export function useChatStream() {
	const [turns, dispatch] = useReducer(chatReducer, [])
	const abort = useRef<AbortController | null>(null)
	const threadId = useRef<string | null>(null)

	const runTurn = useCallback(async (question: string, begin: ChatAction) => {
		abort.current?.abort()
		const controller = new AbortController()
		abort.current = controller
		dispatch(begin)
		try {
			const query = { question, thread_id: threadId.current }
			for await (const event of streamChat(query, controller.signal)) {
				if (event.event === "done") threadId.current = event.data.thread_id
				dispatch(event)
			}
			dispatch({ type: "settle" })
		} catch (error) {
			if (controller.signal.aborted) return
			dispatch({
				type: "fail",
				error: {
					name:
						error instanceof ApiError
							? error.code
							: error instanceof Error
								? error.name
								: "Error",
					message:
						error instanceof Error ? error.message : "Chat request failed",
				},
			})
		}
	}, [])

	const ask = useCallback(
		(question: string) =>
			runTurn(question, { type: "ask", id: randomId(), question }),
		[runTurn],
	)

	/** Reruns the failed last turn in its own place rather than asking it again below. */
	const retry = useCallback(
		(question: string) => runTurn(question, { type: "retry" }),
		[runTurn],
	)

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
		retry,
		stop,
		newThread,
		isBusy: current !== undefined && isTurnRunning(current),
	}
}
