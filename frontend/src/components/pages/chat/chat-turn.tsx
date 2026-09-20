import { CircleAlertIcon, PlusIcon, RotateCcwIcon } from "lucide-react"
import { memo, useCallback, useMemo, useState } from "react"
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
import { CopyAnswerButton } from "./copy-answer-button"
import { RunSteps } from "./run-steps"
import { SourcesPopover, type SourcesView } from "./sources-popover"

const FAILURE_MESSAGES: Record<TurnFailure, string> = {
	thread_full: "Maximum chat turns reached.",
	rate_limited: "Too many questions. Try again in a minute.",
	paused: "Chat is paused for today. Try again tomorrow.",
	unverified: "Couldn't verify your browser. Reload the page and ask again.",
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
	onRetry,
	onNewThread,
}: {
	turn: Turn
	onRetry: () => void
	onNewThread: () => void
}) {
	const [sourcesView, setSourcesView] = useState<SourcesView | null>(null)
	const isSettled = turn.status === "settled"
	const needsCited = isSettled || sourcesView !== null
	const cited = useMemo(
		() => (needsCited ? citedSources(turn.answer, turn.sources) : []),
		[needsCited, turn.answer, turn.sources],
	)

	const openSource = useCallback((marker: number, anchor: Element) => {
		setSourcesView({ marker, anchor })
	}, [])

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
								onOpenMarker={openSource}
							/>
							<div
								className={
									isSettled
										? "fade-in -mx-1 flex animate-in items-center duration-300"
										: "contents"
								}
							>
								{isSettled && (
									<CopyAnswerButton
										answer={turn.answer}
										sources={turn.sources}
									/>
								)}
								<SourcesPopover
									cited={cited}
									view={sourcesView}
									showTrigger={isSettled && cited.length > 0}
									onViewChange={setSourcesView}
								/>
							</div>
						</>
					)}
				</MessageContent>
			</Message>
		</div>
	)
})
