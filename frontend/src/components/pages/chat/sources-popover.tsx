import {
	ArrowLeftIcon,
	ArrowUpRightIcon,
	ChevronDownIcon,
	ChevronLeftIcon,
	ChevronRightIcon,
} from "lucide-react"
import { useRef } from "react"
import { Button } from "@/components/ui/button"
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover"
import type { CitedSource } from "@/lib/citations"
import { cn } from "@/lib/utils"
import { CITATION_BADGE } from "./citation-chip"

const STACKED_BADGES = 3

/** What the popover shows: the list, or one source's text, placed at a marker or the button. */
export type SourcesView = { marker: number | null; anchor: Element | null }

function eurLexUrl(celex: string): string {
	return `https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:${celex}`
}

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

function SourceRows({
	cited,
	onSelect,
}: {
	cited: CitedSource[]
	onSelect: (marker: number) => void
}) {
	return (
		<ul className="flex flex-col">
			{cited.map(({ source, label }) => (
				<li key={source.marker}>
					<button
						type="button"
						onClick={() => onSelect(source.marker)}
						className="grid w-full grid-cols-[18px_minmax(0,1fr)] items-center gap-x-2 rounded-lg px-2 py-1.5 text-left outline-none transition-colors hover:bg-secondary focus-visible:bg-secondary"
					>
						<span className={CITATION_BADGE}>{label}</span>
						<span className="truncate font-medium text-[13px]">
							{source.citation}
						</span>
						<span className="col-start-2 truncate text-faint-foreground text-xs">
							{source.act}
						</span>
					</button>
				</li>
			))}
		</ul>
	)
}

function SourceText({
	cited,
	index,
	onSelect,
	onBack,
}: {
	cited: CitedSource[]
	index: number
	onSelect: (marker: number) => void
	onBack: () => void
}) {
	const { source, label } = cited[index]
	const previous = cited[index - 1]
	const next = cited[index + 1]

	return (
		<div className="flex flex-col">
			<div className="flex items-start gap-2 border-b px-1 pb-2">
				<Button
					variant="ghost"
					size="icon-xs"
					aria-label="All sources"
					onClick={onBack}
					className="rounded-md text-muted-foreground"
				>
					<ArrowLeftIcon />
				</Button>
				<span className={cn(CITATION_BADGE, "mt-0.75")}>{label}</span>
				<div className="min-w-0">
					<p className="font-semibold text-[13px]">{source.citation}</p>
					<p className="truncate text-faint-foreground text-xs">
						{source.act}
						{source.title ? ` · ${source.title}` : ""}
					</p>
				</div>
			</div>
			<div className="max-h-[min(22rem,50dvh)] overflow-y-auto whitespace-pre-wrap px-2 py-2.5 text-muted-foreground text-xs leading-relaxed">
				{source.text}
			</div>
			<div className="flex items-center justify-between border-t px-1 pt-1.5">
				<a
					href={eurLexUrl(source.celex)}
					target="_blank"
					rel="noreferrer"
					className="inline-flex items-center gap-1 rounded-md px-1 py-0.5 text-primary text-xs hover:underline"
				>
					Open in EUR-Lex
					<ArrowUpRightIcon className="size-3" aria-hidden />
				</a>
				{cited.length > 1 && (
					<div className="flex items-center gap-0.5 text-faint-foreground text-xs tabular-nums">
						<Button
							variant="ghost"
							size="icon-xs"
							aria-label="Previous source"
							disabled={previous === undefined}
							onClick={() => previous && onSelect(previous.source.marker)}
							className="rounded-md"
						>
							<ChevronLeftIcon />
						</Button>
						{index + 1} of {cited.length}
						<Button
							variant="ghost"
							size="icon-xs"
							aria-label="Next source"
							disabled={next === undefined}
							onClick={() => next && onSelect(next.source.marker)}
							className="rounded-md"
						>
							<ChevronRightIcon />
						</Button>
					</div>
				)}
			</div>
		</div>
	)
}

/** An answer's sources in one popover: the list from the sources button, or a source's text
 * straight from its citation marker. `showTrigger` is off until the answer settles. */
export function SourcesPopover({
	cited,
	view,
	showTrigger,
	onViewChange,
}: {
	cited: CitedSource[]
	view: SourcesView | null
	showTrigger: boolean
	onViewChange: (view: SourcesView | null) => void
}) {
	const lastOpened = useRef<{ view: SourcesView; cited: CitedSource[] }>(null)
	if (view !== null) lastOpened.current = { view, cited }
	const shown = lastOpened.current
	const shownCited = shown?.cited ?? cited
	const index = shownCited.findIndex(
		({ source }) => source.marker === shown?.view.marker,
	)
	const anchor = shown?.view.anchor ?? undefined

	function select(marker: number) {
		onViewChange({ marker, anchor: view?.anchor ?? null })
	}

	return (
		<Popover
			open={view !== null}
			onOpenChange={(open) =>
				onViewChange(open ? { marker: null, anchor: null } : null)
			}
		>
			{showTrigger && (
				<PopoverTrigger
					render={<Button variant="ghost" size="xs" />}
					className="group ml-1 gap-1.5 rounded-md px-1 font-normal"
				>
					<SourcesLabel cited={cited} />
					<ChevronDownIcon
						aria-hidden
						className="text-muted-foreground transition-transform duration-200 group-data-popup-open:rotate-180"
					/>
				</PopoverTrigger>
			)}
			<PopoverContent
				align="start"
				anchor={anchor}
				className="w-90 max-w-[calc(100vw-2rem)] gap-0 rounded-2xl p-1.5 ring-border"
			>
				{index === -1 ? (
					<SourceRows cited={shownCited} onSelect={select} />
				) : (
					<SourceText
						cited={shownCited}
						index={index}
						onSelect={select}
						onBack={() =>
							onViewChange({ marker: null, anchor: view?.anchor ?? null })
						}
					/>
				)}
			</PopoverContent>
		</Popover>
	)
}
