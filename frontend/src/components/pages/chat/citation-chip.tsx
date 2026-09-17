export const CITATION_BADGE =
	"inline-flex h-4.5 min-w-4.5 shrink-0 items-center justify-center rounded-[5px] bg-primary/12 px-1.25 font-semibold text-[11px] text-primary tabular-nums"

export function CitationChip({
	marker,
	label,
	onOpen,
}: {
	marker: number
	label: number
	onOpen: (marker: number) => void
}) {
	return (
		<button
			type="button"
			aria-label={`Open source ${label}`}
			onClick={() => onOpen(marker)}
			className={`${CITATION_BADGE} relative ml-0.75 align-[1px] leading-none transition-colors after:absolute after:-inset-x-1 after:-inset-y-2 hover:bg-primary/25`}
		>
			{label}
		</button>
	)
}
