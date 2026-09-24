import { type ReactNode, useMemo } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import rehypeKatex from "rehype-katex"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import type { ChatSource } from "@/api/types"
import { numberCitations, rehypeCitationMarkers } from "@/lib/citations"
import { KATEX_OPTIONS, rehypeDisplayFormulas } from "@/lib/formulas"
import { CitationChip } from "./citation-chip"

const PROSE =
	"text-[14.5px] leading-[1.65] [&_h1,&_h2,&_h3,&_h4]:mt-4.5 [&_h1,&_h2,&_h3,&_h4]:mb-1.5 [&_h1,&_h2,&_h3,&_h4]:font-semibold [&_h1,&_h2,&_h3,&_h4]:text-[15.5px] [&_h1,&_h2,&_h3,&_h4]:tracking-[-0.01em] [&>:first-child]:mt-0 [&_p]:mb-2.5 [&_ul]:mb-3 [&_ul]:list-disc [&_ul]:pl-4.5 [&_ol]:mb-3 [&_ol]:list-decimal [&_ol]:pl-4.5 [&_li]:my-0.75 [&_li]:marker:text-faint-foreground [&_strong]:font-semibold [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_table]:w-full [&_table]:text-[13.5px] [&_th,&_td]:px-3 [&_th,&_td]:py-1.5 [&_th,&_td]:align-top [&_th]:bg-muted [&_th:not([align])]:text-left [&_th]:font-semibold [&_td]:border-t"

const MATH_OPTIONS = { singleDollarTextMath: false }

function MarkdownTable({ children }: { children?: ReactNode }) {
	return (
		<div className="mb-3 overflow-x-auto rounded-md border">
			<table>{children}</table>
		</div>
	)
}

export function Answer({
	answer,
	sources,
	onOpenMarker,
}: {
	answer: string
	sources: ChatSource[]
	onOpenMarker: (marker: number, anchor: Element) => void
}) {
	const known = useMemo(
		() => new Set(sources.map((source) => source.marker)),
		[sources],
	)
	const numbers = useMemo(() => numberCitations(answer, known), [answer, known])
	const components = useMemo(
		() =>
			({
				table: MarkdownTable,
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
				remarkPlugins={[remarkGfm, [remarkMath, MATH_OPTIONS]]}
				rehypePlugins={[
					rehypeCitationMarkers(known),
					rehypeDisplayFormulas,
					[rehypeKatex, KATEX_OPTIONS],
				]}
				components={components}
			>
				{answer}
			</ReactMarkdown>
		</div>
	)
}
