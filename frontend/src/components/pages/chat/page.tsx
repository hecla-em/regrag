import { MenuIcon, PlusIcon, XIcon } from "lucide-react"
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
import {
	readSidebarCollapsed,
	storeSidebarCollapsed,
} from "@/lib/sidebar-collapsed"
import { ChatTurn } from "./chat-turn"
import { PromptForm } from "./prompt-form"
import { Sidebar } from "./sidebar"
import { SourceList } from "./source-list"
import { SourcePanel } from "./source-panel"

type OpenMarker = { turnId: string; marker: number } | null

type TurnHandlers = {
	onOpenMarker: (marker: number) => void
	onToggleSources: () => void
	onRetry: () => void
}

export function ChatPage() {
	const { threads, thread, ask, stop, openThread, isBusy } = useChatThreads()
	const [openMarker, setOpenMarker] = useState<OpenMarker>(null)
	const [sourcesTurnId, setSourcesTurnId] = useState<string | null>(null)
	const [isMenuOpen, setIsMenuOpen] = useState(false)
	const [isCollapsed, setIsCollapsed] = useState(readSidebarCollapsed)
	const handlersByTurnId = useRef(new Map<string, TurnHandlers>())
	const turns = thread?.turns ?? []

	function askQuestion(question: string) {
		setOpenMarker(null)
		ask(question)
	}

	const showThread = useCallback(
		(id: string | null) => {
			setOpenMarker(null)
			setSourcesTurnId(null)
			setIsMenuOpen(false)
			openThread(id)
		},
		[openThread],
	)

	const startNewThread = useCallback(() => showThread(null), [showThread])

	function collapseSidebar(collapsed: boolean) {
		setIsCollapsed(collapsed)
		storeSidebarCollapsed(collapsed)
	}

	function getTurnHandlers(turnId: string, question: string): TurnHandlers {
		const cached = handlersByTurnId.current.get(turnId)
		if (cached !== undefined) return cached
		const handlers: TurnHandlers = {
			onOpenMarker: (marker) => setOpenMarker({ turnId, marker }),
			onToggleSources: () =>
				setSourcesTurnId((open) => (open === turnId ? null : turnId)),
			onRetry: () => askQuestion(question),
		}
		handlersByTurnId.current.set(turnId, handlers)
		return handlers
	}

	const sourcesTurn = turns.find((turn) => turn.id === sourcesTurnId)
	const sourcesCited = useMemo(
		() =>
			sourcesTurn ? citedSources(sourcesTurn.answer, sourcesTurn.sources) : [],
		[sourcesTurn],
	)

	const openTurn = turns.find((turn) => turn.id === openMarker?.turnId)
	const openCited = useMemo(
		() => (openTurn ? citedSources(openTurn.answer, openTurn.sources) : []),
		[openTurn],
	)
	const opened = openCited.find(
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
		<div className="flex h-dvh">
			<Sidebar
				{...sidebarProps}
				collapsed={isCollapsed}
				onCollapsedChange={collapseSidebar}
				className="hidden border-r md:flex"
			/>

			<main className="flex min-h-0 min-w-0 flex-1 flex-col">
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
													isSourcesOpen={turn.id === sourcesTurnId}
													onOpenMarker={handlers.onOpenMarker}
													onToggleSources={handlers.onToggleSources}
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
				)}

				<div className="mx-auto w-full max-w-3xl px-4 pt-2 pb-4 md:px-6.5">
					<PromptForm isBusy={isBusy} onSubmit={askQuestion} onStop={stop} />
					<p className="mt-3 text-center text-footnote-foreground text-xs">
						Answers are generated from the official EU texts and may be wrong.
						<br />
						They are not legal advice, so check the cited article.
					</p>
				</div>
				{isEmpty && <div className="flex-1" />}
			</main>

			{sourcesTurn && (
				<aside className="fade-in slide-in-from-right-2 hidden w-70 shrink-0 animate-in flex-col border-l bg-sidebar duration-200 lg:flex">
					<div className="flex h-11.5 shrink-0 items-center justify-between border-b pr-2 pl-4">
						<Eyebrow>Sources</Eyebrow>
						<Button
							variant="ghost"
							size="icon-sm"
							aria-label="Close sources"
							onClick={() => setSourcesTurnId(null)}
							className="text-muted-foreground"
						>
							<XIcon />
						</Button>
					</div>
					<SourceList
						cited={sourcesCited}
						onOpenSource={
							getTurnHandlers(sourcesTurn.id, sourcesTurn.question).onOpenMarker
						}
						className="min-h-0 overflow-y-auto p-3.5"
					/>
				</aside>
			)}

			<Drawer
				open={isMenuOpen}
				onOpenChange={setIsMenuOpen}
				swipeDirection="left"
			>
				<DrawerContent className="data-[swipe-axis=x]:[--drawer-content-width:14rem] data-[swipe-axis=x]:sm:[--drawer-content-width:14rem]">
					<DrawerTitle className="sr-only">Menu</DrawerTitle>
					<Sidebar
						{...sidebarProps}
						className="h-full w-full rounded-[inherit]"
					/>
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
