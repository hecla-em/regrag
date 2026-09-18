import { PlusIcon } from "lucide-react"
import { Eyebrow } from "@/components/shared/eyebrow"
import { HeclaWordmark } from "@/components/shared/hecla-wordmark"
import { Button } from "@/components/ui/button"
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar"
import type { ChatTurn } from "@/lib/chat-turns"
import { cn } from "@/lib/utils"

/** The top bar: the wordmark on the hero while the sidebar hides its own, else the thread's title. */
export function ChatHeader({
	turns,
	isBusy,
	onNewThread,
}: {
	turns: ChatTurn[]
	isBusy: boolean
	onNewThread: () => void
}) {
	const { state, isMobile } = useSidebar()
	const isSidebarWordmarkShown = state === "expanded" && !isMobile

	return (
		<header className="flex h-11.5 shrink-0 items-center gap-2.5 border-b px-3 md:px-5.5">
			<SidebarTrigger className="md:hidden" />
			{turns.length === 0 ? (
				<HeclaWordmark
					aria-hidden={isSidebarWordmarkShown}
					className={cn(
						"mr-auto h-4 text-primary transition-opacity duration-180 ease-[cubic-bezier(0.16,1,0.3,1)]",
						isSidebarWordmarkShown && "opacity-0",
					)}
				/>
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
				onClick={onNewThread}
				disabled={isBusy}
				className="shrink-0 md:hidden"
			>
				<PlusIcon />
			</Button>
		</header>
	)
}
