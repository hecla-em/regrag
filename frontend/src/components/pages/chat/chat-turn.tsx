import { CircleAlertIcon, PlusIcon, RotateCcwIcon } from "lucide-react"
import { memo, useMemo } from "react"
import { Bubble, BubbleContent } from "@/components/ui/bubble"
import { Button } from "@/components/ui/button"
import { Message, MessageContent } from "@/components/ui/message"
import {
	isTurnRunning,
	type ChatTurn as Turn,
	type TurnFailure,
	turnFailure,
} from "@/lib/chat-turns"
import { citedSources } from "@/lib/citations"
import { Answer } from "./answer"
import { AnswerActions } from "./answer-actions"
import { RunSteps } from "./run-steps"
import { SourceList } from "./source-list"

const FAILURE_MESSAGES: Record<TurnFailure, string> = {
	thread_full: "Maximum chat turns reached.",
	rate_limited: "Too many questions. Try again in a minute.",
	paused: "Chat is paused for today. Try again tomorrow.",
	unexpected: "That answer didn't come through.",
}

/** A failed turn as one soft line where its answer would be: a generic reason, and the way on. */
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
		<div
			role="alert"
			className="flex flex-wrap items-center gap-x-2.5 gap-y-2 rounded-xl bg-destructive/8 px-3 py-2.5 text-[13px] text-destructive ring-1 ring-destructive/22 ring-inset"
		>
			<CircleAlertIcon className="size-3.75 shrink-0" aria-hidden />
			<p className="flex-1">{FAILURE_MESSAGES[failure]}</p>
			{failure === "unexpected" && (
				<Button variant="outline" size="xs" onClick={onRetry}>
					<RotateCcwIcon />
					Try again
				</Button>
			)}
			{failure === "thread_full" && (
				<Button variant="outline" size="xs" onClick={onNewThread}>
					<PlusIcon />
					New question
				</Button>
			)}
		</div>
	)
}

export const ChatTurn = memo(function ChatTurn({
	turn,
	isLatest,
	onOpenMarker,
	onRetry,
	onNewThread,
}: {
	turn: Turn
	isLatest: boolean
	onOpenMarker: (marker: number) => void
	onRetry: () => void
	onNewThread: () => void
}) {
	const cited = useMemo(
		() => citedSources(turn.answer, turn.sources),
		[turn.answer, turn.sources],
	)

	return (
		<div className="flex flex-col gap-3.5">
			<Message align="end">
				<MessageContent>
					<Bubble align="end" variant="secondary" className="max-w-[78%]">
						<BubbleContent className="rounded-[14px] rounded-br-[4px] px-3.25 py-2.25">
							{turn.question}
						</BubbleContent>
					</Bubble>
				</MessageContent>
			</Message>
			<Message align="start">
				<MessageContent className="gap-2">
					<RunSteps
						steps={turn.steps}
						isRunning={isTurnRunning(turn)}
						askedAt={turn.askedAt}
					/>
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
								<AnswerActions answer={turn.answer} sources={turn.sources} />
							)}
							{isLatest && cited.length > 0 && (
								<SourceList
									cited={cited}
									onOpenSource={onOpenMarker}
									className="mt-2 lg:hidden"
								/>
							)}
						</>
					)}
				</MessageContent>
			</Message>
		</div>
	)
})
