import { FuelIcon, GaugeIcon, PlusIcon } from "lucide-react"
import { Eyebrow } from "@/components/shared/eyebrow"
import { HeclaWordmark } from "@/components/shared/hecla-wordmark"
import type { TabThread } from "@/lib/chat-threads"
import { cn } from "@/lib/utils"

/** The corpus topics, keyed as the backend's TOPIC_BASE_ACTS keys them. */
const COVERED_TOPICS = [
	{ key: "fueleu", name: "FuelEU Maritime", Icon: FuelIcon },
	{ key: "mrv", name: "MRV", Icon: GaugeIcon },
]

export function Sidebar({
	threads,
	activeId,
	isBusy,
	onOpenThread,
	className,
}: {
	threads: TabThread[]
	activeId: string | null
	isBusy: boolean
	onOpenThread: (id: string | null) => void
	className?: string
}) {
	return (
		<nav
			aria-label="Questions"
			className={cn(
				"flex min-h-0 flex-col gap-4 bg-sidebar px-3 py-4 text-sidebar-foreground",
				className,
			)}
		>
			<HeclaWordmark className="mx-1 my-0.5 h-5 self-start text-primary" />
			<button
				type="button"
				onClick={() => onOpenThread(null)}
				disabled={isBusy}
				className="flex h-8.5 items-center gap-2 rounded-lg bg-secondary px-2.5 font-medium text-[13px] ring-1 ring-input transition-colors hover:bg-accent disabled:opacity-50"
			>
				<PlusIcon size={15} aria-hidden />
				New question
			</button>
			{threads.length > 0 && (
				<section className="flex min-h-0 flex-col gap-1.5">
					<Eyebrow className="px-2.5">Your questions</Eyebrow>
					<ul className="flex min-h-0 flex-col overflow-y-auto">
						{threads.map((thread) => (
							<li key={thread.id}>
								<button
									type="button"
									onClick={() => onOpenThread(thread.id)}
									disabled={isBusy && thread.id !== activeId}
									aria-current={thread.id === activeId ? "page" : undefined}
									className="w-full truncate rounded-lg px-2.5 py-1.75 text-left text-[12.5px] text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground disabled:opacity-50 aria-[current=page]:bg-sidebar-accent aria-[current=page]:text-sidebar-accent-foreground"
								>
									{thread.turns[0]?.question}
								</button>
							</li>
						))}
					</ul>
				</section>
			)}
			<section className="flex flex-col gap-1.5">
				<Eyebrow className="px-2.5">Covers</Eyebrow>
				<ul>
					{COVERED_TOPICS.map(({ key, name, Icon }) => (
						<li
							key={key}
							className="flex items-center gap-2 px-2.5 py-1.25 text-[12.5px] text-muted-foreground"
						>
							<Icon size={13} aria-hidden />
							{name}
						</li>
					))}
				</ul>
			</section>
			<p className="mt-auto px-1.5 text-[10.5px] text-faint-foreground leading-normal">
				Generated from the official EU texts and may be wrong. Not legal advice,
				so check the cited article.
			</p>
		</nav>
	)
}
