import { PlusIcon } from "lucide-react"
import { useCallback, useRef, useState } from "react"
import { HeclaWordmark } from "@/components/shared/hecla-wordmark"
import { Button } from "@/components/ui/button"
import {
	MessageScroller,
	MessageScrollerButton,
	MessageScrollerContent,
	MessageScrollerItem,
	MessageScrollerProvider,
	MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { useChatStream } from "@/hooks/use-chat-stream"
import { citedSources } from "@/lib/citations"
import { ChatTurn } from "./chat-turn"
import { PromptForm } from "./prompt-form"
import { SourcePanel } from "./source-panel"

type OpenMarker = { turnId: string; marker: number } | null

type TurnHandlers = {
	onOpenMarker: (marker: number) => void
	onRetry: () => void
}

export function ChatPage() {
	const { turns, ask, stop, newThread, isBusy } = useChatStream()
	const [openMarker, setOpenMarker] = useState<OpenMarker>(null)
	const handlersByTurnId = useRef(new Map<string, TurnHandlers>())

	function askQuestion(question: string) {
		setOpenMarker(null)
		ask(question)
	}

	const startNewThread = useCallback(() => {
		setOpenMarker(null)
		newThread()
	}, [newThread])

	function getTurnHandlers(turnId: string, question: string): TurnHandlers {
		const cached = handlersByTurnId.current.get(turnId)
		if (cached !== undefined) return cached
		const handlers: TurnHandlers = {
			onOpenMarker: (marker) => setOpenMarker({ turnId, marker }),
			onRetry: () => askQuestion(question),
		}
		handlersByTurnId.current.set(turnId, handlers)
		return handlers
	}

	const openTurn = turns.find((turn) => turn.id === openMarker?.turnId)
	const opened =
		openTurn === undefined
			? undefined
			: citedSources(openTurn.answer, openTurn.sources).find(
					(cited) => cited.source.marker === openMarker?.marker,
				)

	const isEmpty = turns.length === 0

	return (
		<main className="mx-auto flex h-dvh w-full max-w-3xl flex-col">
			{isEmpty ? (
				<div className="flex flex-1 flex-col items-center justify-end gap-6 px-6 pb-8">
					<HeclaWordmark className="h-8 text-primary" />
					<h1 className="text-center font-semibold text-3xl tracking-tight">
						Ask about EU maritime regulation
					</h1>
				</div>
			) : (
				<>
					<div className="flex justify-end px-6 pt-4">
						<Button
							variant="outline"
							size="sm"
							onClick={startNewThread}
							disabled={isBusy}
						>
							<PlusIcon />
							New thread
						</Button>
					</div>
					<MessageScrollerProvider>
						<MessageScroller className="flex-1">
							<MessageScrollerViewport>
								<MessageScrollerContent className="flex flex-col gap-8 px-6 py-6">
									{turns.map((turn) => {
										const handlers = getTurnHandlers(turn.id, turn.question)
										return (
											<MessageScrollerItem
												key={turn.id}
												messageId={turn.id}
												scrollAnchor
											>
												<ChatTurn
													turn={turn}
													onOpenMarker={handlers.onOpenMarker}
													onRetry={handlers.onRetry}
													onNewThread={startNewThread}
												/>
											</MessageScrollerItem>
										)
									})}
								</MessageScrollerContent>
							</MessageScrollerViewport>
							<MessageScrollerButton />
						</MessageScroller>
					</MessageScrollerProvider>
				</>
			)}
			<div className="px-6 pb-6">
				<PromptForm isBusy={isBusy} onSubmit={askQuestion} onStop={stop} />
				<p className="mt-3 text-center text-faint-foreground text-xs">
					Answers are generated from the official EU texts and may be wrong.
					<br />
					They are not legal advice, so check the cited article.
				</p>
			</div>
			{isEmpty && <div className="flex-1" />}
			<SourcePanel
				source={opened?.source ?? null}
				label={opened?.label ?? null}
				onClose={() => setOpenMarker(null)}
			/>
		</main>
	)
}
