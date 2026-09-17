import {
	FuelIcon,
	GaugeIcon,
	PanelLeftCloseIcon,
	PanelLeftOpenIcon,
	SquarePenIcon,
} from "lucide-react"
import { Eyebrow } from "@/components/shared/eyebrow"
import { HeclaWordmark } from "@/components/shared/hecla-wordmark"
import { Button } from "@/components/ui/button"
import type { TabThread } from "@/lib/chat-threads"
import { cn } from "@/lib/utils"

/** The corpus topics, keyed as the backend's TOPIC_BASE_ACTS keys them. */
const COVERED_TOPICS = [
	{ key: "fueleu", name: "FuelEU Maritime", Icon: FuelIcon },
	{ key: "mrv", name: "MRV", Icon: GaugeIcon },
]

const EASE = "ease-[cubic-bezier(0.16,1,0.3,1)]"

const COPY = cn(
	"transition-[opacity,translate] duration-180 group-data-collapsed/sidebar:pointer-events-none group-data-collapsed/sidebar:-translate-x-2 group-data-collapsed/sidebar:opacity-0",
	EASE,
)

const ROW =
	"mx-2 h-8 w-52 justify-start gap-1.5 rounded-lg px-2 text-[13px] text-muted-foreground hover:text-foreground group-data-collapsed/sidebar:w-9"

/** Labels fade as the sidebar narrows to its icons, and every icon keeps its place. The toggle
 * shows only where `onCollapsedChange` is given, so the mobile drawer always opens expanded. */
export function Sidebar({
	threads,
	activeId,
	isBusy,
	collapsed = false,
	onOpenThread,
	onCollapsedChange,
	className,
}: {
	threads: TabThread[]
	activeId: string | null
	isBusy: boolean
	collapsed?: boolean
	onOpenThread: (id: string | null) => void
	onCollapsedChange?: (collapsed: boolean) => void
	className?: string
}) {
	return (
		<nav
			aria-label="Chats"
			data-collapsed={collapsed || undefined}
			className={cn(
				"group/sidebar flex min-h-0 shrink-0 overflow-hidden bg-sidebar py-2 text-sidebar-foreground transition-[width] duration-280",
				EASE,
				collapsed ? "w-13" : "w-56",
				className,
			)}
		>
			<div className="flex min-h-0 w-56 shrink-0 flex-col">
				<div className="relative mb-2 h-10 shrink-0">
					<HeclaWordmark
						className={cn("absolute top-3.5 left-4 h-4 text-primary", COPY)}
					/>
					{onCollapsedChange && (
						<>
							<Button
								variant="ghost"
								size="icon-sm"
								aria-label="Collapse sidebar"
								inert={collapsed}
								onClick={() => onCollapsedChange(true)}
								className={cn(
									"absolute top-1.5 right-2 text-muted-foreground",
									COPY,
								)}
							>
								<PanelLeftCloseIcon />
							</Button>
							<Button
								variant="ghost"
								size="icon-sm"
								aria-label="Expand sidebar"
								inert={!collapsed}
								onClick={() => onCollapsedChange(false)}
								className="pointer-events-none absolute top-1.5 left-3 text-muted-foreground opacity-0 transition-opacity group-data-collapsed/sidebar:pointer-events-auto group-data-collapsed/sidebar:opacity-100"
							>
								<PanelLeftOpenIcon />
							</Button>
						</>
					)}
				</div>

				<Button
					variant="ghost"
					title="New question"
					onClick={() => onOpenThread(null)}
					disabled={isBusy}
					className={cn(ROW, "font-medium text-foreground")}
				>
					<span className="flex size-5 shrink-0 items-center justify-center">
						<SquarePenIcon />
					</span>
					<span className={COPY}>New question</span>
				</Button>

				<section className="mt-4 flex flex-col gap-1">
					<Eyebrow className={cn("mx-2 px-2", COPY)}>Topics</Eyebrow>
					<ul className="flex flex-col gap-px">
						{COVERED_TOPICS.map(({ key, name, Icon }) => (
							<li
								key={key}
								title={name}
								className="mx-2 flex h-8 items-center gap-1.5 px-2 text-[13px] text-muted-foreground"
							>
								<span className="flex size-5 shrink-0 items-center justify-center">
									<Icon size={16} aria-hidden />
								</span>
								<span className={cn("truncate", COPY)}>{name}</span>
							</li>
						))}
					</ul>
				</section>

				<section
					inert={collapsed}
					className={cn("mt-4 flex min-h-0 flex-1 flex-col gap-1", COPY)}
				>
					<Eyebrow className="mx-2 px-2">Chats</Eyebrow>
					{threads.length === 0 ? (
						<p className="mx-2 px-2 py-1.5 text-[12.5px] text-faint-foreground">
							No chats yet
						</p>
					) : (
						<ul className="flex min-h-0 flex-col gap-px overflow-y-auto">
							{threads.map((thread) => (
								<li key={thread.id}>
									<Button
										variant="ghost"
										onClick={() => onOpenThread(thread.id)}
										disabled={isBusy && thread.id !== activeId}
										aria-current={thread.id === activeId ? "page" : undefined}
										className={cn(
											ROW,
											"font-normal aria-[current=page]:bg-sidebar-accent aria-[current=page]:text-sidebar-accent-foreground",
										)}
									>
										<span className="truncate">
											{thread.turns[0]?.question}
										</span>
									</Button>
								</li>
							))}
						</ul>
					)}
				</section>
			</div>
		</nav>
	)
}
