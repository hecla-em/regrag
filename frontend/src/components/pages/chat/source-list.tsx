import type { CitedSource } from "@/lib/citations"
import { cn } from "@/lib/utils"
import { CITATION_BADGE } from "./citation-chip"

/** The sources an answer cites as cards, numbered as the answer numbered them. */
export function SourceList({
	cited,
	onOpenSource,
	className,
}: {
	cited: CitedSource[]
	onOpenSource: (marker: number) => void
	className?: string
}) {
	return (
		<ul className={cn("flex flex-col gap-2", className)}>
			{cited.map(({ source, label }) => (
				<li key={source.marker}>
					<button
						type="button"
						onClick={() => onOpenSource(source.marker)}
						className="flex w-full flex-col gap-1 rounded-xl bg-muted p-3 text-left ring-1 ring-border transition-colors hover:bg-secondary"
					>
						<span className="flex items-center gap-2">
							<span className={CITATION_BADGE}>{label}</span>
							<span className="truncate font-semibold text-[13px]">
								{source.citation}
							</span>
						</span>
						<span className="truncate pl-6.5 text-faint-foreground text-xs">
							{source.act}
						</span>
					</button>
				</li>
			))}
		</ul>
	)
}
