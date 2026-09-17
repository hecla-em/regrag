import { CircleAlertIcon, PlusIcon, RotateCcwIcon } from "lucide-react"
import { memo } from "react"
import { Bubble, BubbleContent } from "@/components/ui/bubble"
import { Button } from "@/components/ui/button"
import { Message, MessageContent } from "@/components/ui/message"
import {
	isTurnRunning,
	type ChatTurn as Turn,
	type TurnFailure,
	turnFailure,
} from "@/lib/chat-turns"
import { Answer } from "./answer"
import { AnswerActions } from "./answer-actions"
import { RunSteps } from "./run-steps"

const FAILURE_MESSAGES: Record<TurnFailure, string> = {
	thread_full: "Maximum chat turns reached.",
	rate_limited: "Too many questions. Try again in a minute.",
	paused: "Chat is paused for today. Try again tomorrow.",
	unexpected: "Something went wrong.",
}

/** A failed turn as one line where its answer would be: a generic reason, and the way on. */
function TurnError({
	turn,
	onRetry,
	onNewThread,
}: {
	turn: Turn
	onRetry: () => void
	onNewThread: () => void
}) {
	const failure = turnFailure(turn)
	return (
		<div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-2">
			<p className="flex items-start gap-2 text-destructive text-sm">
				<CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
				{FAILURE_MESSAGES[failure]}
			</p>
			{failure === "unexpected" && (
				<Button variant="outline" size="xs" onClick={onRetry}>
					<RotateCcwIcon />
					Retry
				</Button>
			)}
			{failure === "thread_full" && (
				<Button variant="outline" size="xs" onClick={onNewThread}>
					<PlusIcon />
					New thread
				</Button>
			)}
		</div>
	)
}

export const ChatTurn = memo(function ChatTurn({
	turn,
	onOpenMarker,
	onRetry,
	onNewThread,
}: {
	turn: Turn
	onOpenMarker: (marker: number) => void
	onRetry: () => void
	onNewThread: () => void
}) {
	return (
		<div className="flex flex-col gap-4">
			<Message align="end">
				<MessageContent>
					<Bubble align="end">
						<BubbleContent>{turn.question}</BubbleContent>
					</Bubble>
				</MessageContent>
			</Message>
			<Message align="start">
				<MessageContent>
					<RunSteps steps={turn.steps} isRunning={isTurnRunning(turn)} />
					{turn.status === "failed" ? (
						<TurnError
							turn={turn}
							onRetry={onRetry}
							onNewThread={onNewThread}
						/>
					) : (
						<>
							<Answer
								answer={turn.answer}
								sources={turn.sources}
								onOpenMarker={onOpenMarker}
							/>
							{turn.status === "settled" && (
								<AnswerActions
									answer={turn.answer}
									sources={turn.sources}
									onOpenSource={onOpenMarker}
								/>
							)}
						</>
					)}
				</MessageContent>
			</Message>
		</div>
	)
})
