import { FuelIcon, GaugeIcon, LandmarkIcon, SquarePenIcon } from "lucide-react"
import { EYEBROW } from "@/components/shared/eyebrow"
import { HeclaWordmark } from "@/components/shared/hecla-wordmark"
import {
	Sidebar,
	SidebarContent,
	SidebarGroup,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarTrigger,
	useSidebar,
} from "@/components/ui/sidebar"
import type { TabThread } from "@/lib/chat-threads"
import { cn } from "@/lib/utils"

/** The corpus topics, keyed as the backend's TOPIC_BASE_ACTS keys them. */
const COVERED_TOPICS = [
	{ key: "fueleu", name: "FuelEU Maritime", Icon: FuelIcon },
	{ key: "mrv", name: "MRV", Icon: GaugeIcon },
	{ key: "ets", name: "EU ETS", Icon: LandmarkIcon },
]

/** Collapsing fades the words in place, so no icon moves. */
const FADE =
	"transition-[opacity,translate] duration-180 ease-[cubic-bezier(0.16,1,0.3,1)] group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-translate-x-2 group-data-[collapsible=icon]:opacity-0"

const GROUP_LABEL = cn(
	"h-6 px-2 font-normal group-data-[collapsible=icon]:mt-0",
	EYEBROW,
)

const ROW = "has-[>svg:first-child]:pl-2"

/** Narrows to its icons on desktop and opens as a sheet on mobile. Opening a chat closes the sheet. */
export function ChatSidebar({
	threads,
	activeId,
	isBusy,
	onOpenThread,
}: {
	threads: TabThread[]
	activeId: string | null
	isBusy: boolean
	onOpenThread: (id: string | null) => void
}) {
	const { state, isMobile, setOpenMobile } = useSidebar()
	const isCollapsed = state === "collapsed" && !isMobile

	function openThread(id: string | null) {
		setOpenMobile(false)
		onOpenThread(id)
	}

	return (
		<Sidebar collapsible="icon">
			<SidebarHeader className="relative h-12">
				<HeclaWordmark
					className={cn("absolute top-4 left-4 h-4 text-primary", FADE)}
				/>
				<SidebarTrigger className="absolute top-2.5 right-2.5 text-muted-foreground" />
			</SidebarHeader>

			<SidebarContent>
				<SidebarGroup className="py-0">
					<SidebarMenu>
						<SidebarMenuItem>
							<SidebarMenuButton
								tooltip="New question"
								onClick={() => openThread(null)}
								disabled={isBusy}
								className={cn(ROW, "font-medium")}
							>
								<SquarePenIcon />
								<span className={FADE}>New question</span>
							</SidebarMenuButton>
						</SidebarMenuItem>
					</SidebarMenu>
				</SidebarGroup>

				<SidebarGroup>
					<SidebarGroupLabel className={cn(GROUP_LABEL, FADE)}>
						Topics
					</SidebarGroupLabel>
					<SidebarMenu>
						{COVERED_TOPICS.map(({ key, name, Icon }) => (
							<SidebarMenuItem key={key}>
								<SidebarMenuButton
									tooltip={name}
									render={<div />}
									className={cn(
										ROW,
										"cursor-default text-muted-foreground hover:bg-transparent hover:text-muted-foreground",
									)}
								>
									<Icon />
									<span className={FADE}>{name}</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
						))}
					</SidebarMenu>
				</SidebarGroup>

				<SidebarGroup
					inert={isCollapsed}
					className={cn("min-h-0 flex-1", FADE)}
				>
					<SidebarGroupLabel className={GROUP_LABEL}>Chats</SidebarGroupLabel>
					{threads.length === 0 ? (
						<p className="px-2 py-1.5 text-[12.5px] text-faint-foreground">
							No chats yet
						</p>
					) : (
						<SidebarMenu className="min-h-0 overflow-y-auto">
							{threads.map((thread) => (
								<SidebarMenuItem key={thread.id}>
									<SidebarMenuButton
										isActive={thread.id === activeId}
										aria-current={thread.id === activeId ? "page" : undefined}
										onClick={() => openThread(thread.id)}
										disabled={isBusy && thread.id !== activeId}
										className="text-muted-foreground"
									>
										<span>{thread.turns[0]?.question}</span>
									</SidebarMenuButton>
								</SidebarMenuItem>
							))}
						</SidebarMenu>
					)}
				</SidebarGroup>
			</SidebarContent>
		</Sidebar>
	)
}
