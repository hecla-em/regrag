import { type CSSProperties, useCallback, useRef } from "react"
import { ShipDrawing } from "@/components/shared/ship-drawing"
import {
	MessageScroller,
	MessageScrollerButton,
	MessageScrollerContent,
	MessageScrollerItem,
	MessageScrollerProvider,
	MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { useChatThreads } from "@/hooks/use-chat-threads"
import { readSidebarOpen } from "@/lib/sidebar-open"
import { cn } from "@/lib/utils"
import { ChatTurn } from "./chat-turn"
import { ChatHeader } from "./header"
import { PromptForm } from "./prompt-form"
import { ChatSidebar } from "./sidebar"

export function ChatPage() {
	const { threads, thread, ask, stop, openThread, isBusy } = useChatThreads()
	const retriesByTurnId = useRef(new Map<string, () => void>())
	const turns = thread?.turns ?? []

	const startNewThread = useCallback(() => openThread(null), [openThread])

	/** One retry per turn, kept stable so a settled turn does not re-render as others stream. */
	function getRetry(turnId: string, question: string): () => void {
		const cached = retriesByTurnId.current.get(turnId)
		if (cached !== undefined) return cached
		const retry = () => ask(question)
		retriesByTurnId.current.set(turnId, retry)
		return retry
	}

	const isHero = turns.length === 0

	return (
		<SidebarProvider
			defaultOpen={readSidebarOpen()}
			className="h-dvh min-h-0"
			style={{ "--sidebar-width": "14rem" } as CSSProperties}
		>
			<ChatSidebar
				threads={threads}
				activeId={thread?.id ?? null}
				isBusy={isBusy}
				onOpenThread={openThread}
			/>

			<SidebarInset className="relative min-h-0 min-w-0">
				<ChatHeader
					turns={turns}
					isBusy={isBusy}
					onNewThread={startNewThread}
				/>

				{isHero ? (
					<div className="relative flex min-h-0 flex-1 flex-col items-center justify-end gap-6 px-6 pb-8">
						<ShipDrawing className="w-28 text-foreground" />
						<h2 className="text-center font-semibold text-3xl tracking-tight">
							Ask about EU maritime regulation
						</h2>
					</div>
				) : (
					<MessageScrollerProvider key={thread?.id}>
						<MessageScroller className="flex-1">
							<MessageScrollerViewport>
								<MessageScrollerContent className="mx-auto w-full max-w-3xl gap-8 px-4 py-5 md:px-6.5">
									{turns.map((turn) => (
										<MessageScrollerItem
											key={turn.id}
											messageId={turn.id}
											scrollAnchor
										>
											<ChatTurn
												turn={turn}
												onRetry={getRetry(turn.id, turn.question)}
												onNewThread={startNewThread}
											/>
										</MessageScrollerItem>
									))}
								</MessageScrollerContent>
							</MessageScrollerViewport>
							<MessageScrollerButton />
						</MessageScroller>
					</MessageScrollerProvider>
				)}

				<div
					className={cn(
						"relative mx-auto w-full max-w-3xl px-4 pt-2 pb-4 md:px-6.5",
						isHero && "md:w-[calc(100%-6rem)]",
					)}
				>
					<PromptForm isBusy={isBusy} onSubmit={ask} onStop={stop} />
					<p className="mt-4 text-center text-footnote-foreground text-xs">
						Answers are generated from the official EU texts and may be wrong.
						<br />
						They are not legal advice, so check the cited article.
					</p>
				</div>
				{isHero && <div aria-hidden="true" className="floor-grid flex-1" />}
			</SidebarInset>
		</SidebarProvider>
	)
}
