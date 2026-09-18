import { PlusIcon } from "lucide-react"
import { type CSSProperties, useCallback, useRef } from "react"
import { Eyebrow } from "@/components/shared/eyebrow"
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
import {
	SidebarInset,
	SidebarProvider,
	SidebarTrigger,
} from "@/components/ui/sidebar"
import { useChatThreads } from "@/hooks/use-chat-threads"
import { readSidebarOpen } from "@/lib/sidebar-open"
import { ChatTurn } from "./chat-turn"
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

	const isEmpty = turns.length === 0

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

			<SidebarInset className="min-h-0 min-w-0">
				<header className="flex h-11.5 shrink-0 items-center gap-2.5 border-b px-3 md:px-5.5">
					<SidebarTrigger className="md:hidden" />
					{isEmpty ? (
						<HeclaWordmark className="mr-auto h-4 text-primary md:hidden" />
					) : (
						<>
							<h1 className="mr-auto min-w-0 truncate font-medium text-[13px]">
								{turns[0].question}
							</h1>
							<Eyebrow className="hidden shrink-0 sm:block">
								{turns.length} {turns.length === 1 ? "question" : "questions"}
							</Eyebrow>
						</>
					)}
					<Button
						variant="ghost"
						size="icon-sm"
						aria-label="New question"
						onClick={startNewThread}
						disabled={isBusy}
						className="shrink-0 md:hidden"
					>
						<PlusIcon />
					</Button>
				</header>

				{isEmpty ? (
					<div className="flex flex-1 flex-col items-center justify-end px-6 pb-8">
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

				<div className="mx-auto w-full max-w-3xl px-4 pt-2 pb-4 md:px-6.5">
					<PromptForm isBusy={isBusy} onSubmit={ask} onStop={stop} />
					<p className="mt-3 text-center text-footnote-foreground text-xs">
						Answers are generated from the official EU texts and may be wrong.
						<br />
						They are not legal advice, so check the cited article.
					</p>
				</div>
				{isEmpty && <div className="flex-1" />}
			</SidebarInset>
		</SidebarProvider>
	)
}
