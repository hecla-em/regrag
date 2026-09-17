import { useMemo } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import type { ChatSource } from "@/api/types"
import { numberCitations, rehypeCitationMarkers } from "@/lib/citations"
import { CitationChip } from "./citation-chip"

const PROSE =
	"text-[14.5px] leading-[1.65] [&_h1,&_h2,&_h3,&_h4]:mt-4.5 [&_h1,&_h2,&_h3,&_h4]:mb-1.5 [&_h1,&_h2,&_h3,&_h4]:font-semibold [&_h1,&_h2,&_h3,&_h4]:text-[15.5px] [&_h1,&_h2,&_h3,&_h4]:tracking-[-0.01em] [&>:first-child]:mt-0 [&_p]:mb-2.5 [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-4.5 [&_ol]:mb-3 [&_ol]:list-decimal [&_ol]:pl-4.5 [&_li]:my-0.75 [&_li]:marker:text-faint-foreground [&_strong]:font-semibold [&_code]:rounded [&_code]:bg-muted [&_code]:px-1"

export function Answer({
	answer,
	sources,
	onOpenMarker,
}: {
	answer: string
	sources: ChatSource[]
	onOpenMarker: (marker: number) => void
}) {
	const known = useMemo(
		() => new Set(sources.map((source) => source.marker)),
		[sources],
	)
	const numbers = useMemo(() => numberCitations(answer, known), [answer, known])
	const components = useMemo(
		() =>
			({
				"cite-marker": ({ marker }: { marker?: string }) => {
					const key = Number(marker)
					return (
						<CitationChip
							marker={key}
							label={numbers.get(key) ?? key}
							onOpen={onOpenMarker}
						/>
					)
				},
			}) as Components,
		[numbers, onOpenMarker],
	)

	return (
		<div className={PROSE}>
			<ReactMarkdown
				remarkPlugins={[remarkGfm]}
				rehypePlugins={[rehypeCitationMarkers(known)]}
				components={components}
			>
				{answer}
			</ReactMarkdown>
		</div>
	)
}
