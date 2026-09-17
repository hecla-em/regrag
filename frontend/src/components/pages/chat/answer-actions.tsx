import { Collapsible } from "@base-ui/react/collapsible"
import { ChevronDownIcon } from "lucide-react"
import { useMemo } from "react"
import type { ChatSource } from "@/api/types"
import { Button } from "@/components/ui/button"
import { type CitedSource, citedSources } from "@/lib/citations"
import { cn } from "@/lib/utils"
import { CITATION_BADGE } from "./citation-chip"
import { CopyAnswerButton } from "./copy-answer-button"
import { SourceList } from "./source-list"

const STACKED_BADGES = 3

function SourcesLabel({ cited }: { cited: CitedSource[] }) {
	return (
		<>
			<span aria-hidden className="flex -space-x-1">
				{cited.slice(0, STACKED_BADGES).map(({ source, label }) => (
					<span
						key={source.marker}
						className={cn(
							CITATION_BADGE,
							"bg-[color-mix(in_oklch,var(--primary)_16%,var(--background))] ring-[1.5px] ring-background",
						)}
					>
						{label}
					</span>
				))}
			</span>
			<span className="text-muted-foreground text-xs">
				{cited.length} {cited.length === 1 ? "source" : "sources"}
			</span>
		</>
	)
}

/** What a reader can do with a settled answer: copy it, and see the sources it cites. One open
 * state drives both views: the side panel on wide screens, the list under the answer on narrow. */
export function AnswerActions({
	answer,
	sources,
	isSourcesOpen,
	onToggleSources,
	onOpenSource,
}: {
	answer: string
	sources: ChatSource[]
	isSourcesOpen: boolean
	onToggleSources: () => void
	onOpenSource: (marker: number) => void
}) {
	const cited = useMemo(() => citedSources(answer, sources), [answer, sources])

	return (
		<Collapsible.Root
			open={isSourcesOpen}
			onOpenChange={onToggleSources}
			className="fade-in flex animate-in flex-col duration-300"
		>
			<div className="-mx-1 flex items-center">
				<CopyAnswerButton answer={answer} sources={sources} />
				{cited.length > 0 && (
					<Collapsible.Trigger
						render={<Button variant="ghost" size="xs" />}
						className="group ml-1 gap-1.5 rounded-md px-1 font-normal"
					>
						<SourcesLabel cited={cited} />
						<ChevronDownIcon
							aria-hidden
							className="text-muted-foreground transition-transform duration-300 group-data-panel-open:rotate-180 lg:hidden"
						/>
					</Collapsible.Trigger>
				)}
			</div>
			<Collapsible.Panel className="h-(--collapsible-panel-height) overflow-hidden transition-[height,opacity] duration-300 ease-[cubic-bezier(0.23,1,0.32,1)] data-ending-style:h-0 data-ending-style:opacity-0 data-starting-style:h-0 data-starting-style:opacity-0 lg:hidden">
				<SourceList
					cited={cited}
					onOpenSource={onOpenSource}
					className="pt-2"
				/>
			</Collapsible.Panel>
		</Collapsible.Root>
	)
}
