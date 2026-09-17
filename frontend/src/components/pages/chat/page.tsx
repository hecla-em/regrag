import { MenuIcon, PlusIcon } from "lucide-react"
import { useCallback, useMemo, useRef, useState } from "react"
import { Eyebrow } from "@/components/shared/eyebrow"
import { HeclaWordmark } from "@/components/shared/hecla-wordmark"
import { Button } from "@/components/ui/button"
import { Drawer, DrawerContent, DrawerTitle } from "@/components/ui/drawer"
import {
	MessageScroller,
	MessageScrollerButton,
	MessageScrollerContent,
	MessageScrollerItem,
	MessageScrollerProvider,
	MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { useChatThreads } from "@/hooks/use-chat-threads"
import { citedSources } from "@/lib/citations"
import { ChatTurn } from "./chat-turn"
import { PromptForm } from "./prompt-form"
import { NOT_LEGAL_ADVICE, Sidebar } from "./sidebar"
import { SourceList } from "./source-list"
import { SourcePanel } from "./source-panel"

type OpenMarker = { turnId: string; marker: number } | null

type TurnHandlers = {
	onOpenMarker: (marker: number) => void
	onRetry: () => void
}

export function ChatPage() {
	const { threads, thread, ask, stop, openThread, isBusy } = useChatThreads()
	const [openMarker, setOpenMarker] = useState<OpenMarker>(null)
	const [isMenuOpen, setIsMenuOpen] = useState(false)
	const handlersByTurnId = useRef(new Map<string, TurnHandlers>())
	const turns = thread?.turns ?? []

	function askQuestion(question: string) {
		setOpenMarker(null)
		ask(question)
	}

	const showThread = useCallback(
		(id: string | null) => {
			setOpenMarker(null)
			setIsMenuOpen(false)
			openThread(id)
		},
		[openThread],
	)

	const startNewThread = useCallback(() => showThread(null), [showThread])

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

	const latest = turns.at(-1)
	const latestAnswer = latest?.answer ?? ""
	const latestSources =
		latest?.status === "failed" ? undefined : latest?.sources
	const latestCited = useMemo(
		() => (latestSources ? citedSources(latestAnswer, latestSources) : []),
		[latestAnswer, latestSources],
	)
	function openLatestSource(marker: number) {
		if (latest) setOpenMarker({ turnId: latest.id, marker })
	}

	const openTurn = turns.find((turn) => turn.id === openMarker?.turnId)
	const opened =
		openTurn === undefined
			? undefined
			: citedSources(openTurn.answer, openTurn.sources).find(
					(cited) => cited.source.marker === openMarker?.marker,
				)

	const isEmpty = turns.length === 0
	const sidebarProps = {
		threads,
		activeId: thread?.id ?? null,
		isBusy,
		onOpenThread: showThread,
	}

	return (
		<div className="grid h-dvh grid-cols-1 md:grid-cols-[188px_minmax(0,1fr)] lg:grid-cols-[188px_minmax(0,1fr)_250px]">
			<Sidebar {...sidebarProps} className="hidden border-r md:flex" />

			<main className="flex min-h-0 min-w-0 flex-col">
				<header className="flex h-11.5 shrink-0 items-center gap-2.5 border-b px-3 md:px-5.5">
					<Button
						variant="ghost"
						size="icon-sm"
						aria-label="Open menu"
						onClick={() => setIsMenuOpen(true)}
						className="md:hidden"
					>
						<MenuIcon />
					</Button>
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
									{latestCited.length > 0 && (
										<SourceList
											cited={latestCited}
											onOpenSource={openLatestSource}
											className="-mt-4 lg:hidden"
										/>
									)}
								</MessageScrollerContent>
							</MessageScrollerViewport>
							<MessageScrollerButton />
						</MessageScroller>
					</MessageScrollerProvider>
				)}

				<div className="mx-auto w-full max-w-3xl px-4 pt-2 pb-4 md:px-6.5">
					<PromptForm isBusy={isBusy} onSubmit={askQuestion} onStop={stop} />
					<p className="mt-2 text-center text-[11px] text-faint-foreground md:hidden">
						{NOT_LEGAL_ADVICE}
					</p>
				</div>
				{isEmpty && <div className="flex-1" />}
			</main>

			<aside className="hidden min-h-0 overflow-y-auto border-l bg-sidebar px-3.5 py-4 lg:block">
				<SourceList cited={latestCited} onOpenSource={openLatestSource} />
			</aside>

			<Drawer
				open={isMenuOpen}
				onOpenChange={setIsMenuOpen}
				swipeDirection="left"
			>
				<DrawerContent className="data-[swipe-axis=x]:[--drawer-content-width:16rem] data-[swipe-axis=x]:sm:[--drawer-content-width:16rem]">
					<DrawerTitle className="sr-only">Menu</DrawerTitle>
					<Sidebar {...sidebarProps} className="flex-1 rounded-[inherit]" />
				</DrawerContent>
			</Drawer>

			<SourcePanel
				source={opened?.source ?? null}
				label={opened?.label ?? null}
				onClose={() => setOpenMarker(null)}
			/>
		</div>
	)
}
