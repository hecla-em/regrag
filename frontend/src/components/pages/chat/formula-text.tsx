import katex from "katex"
import { useMemo } from "react"
import { KATEX_OPTIONS, splitFormulas } from "@/lib/formulas"

/** Source text as written, with each `$$latex$$` the ingest put there typeset by KaTeX. */
export function FormulaText({ text }: { text: string }) {
	return useMemo(
		() =>
			splitFormulas(text).map((segment, index) =>
				segment.kind === "text" ? (
					segment.value
				) : (
					<span
						// biome-ignore lint/suspicious/noArrayIndexKey: the parts of a fixed text never reorder
						key={index}
						// biome-ignore lint/security/noDangerouslySetInnerHtml: KaTeX escapes its input and trust is off
						dangerouslySetInnerHTML={{
							__html: katex.renderToString(segment.latex, {
								...KATEX_OPTIONS,
								displayMode: segment.display,
								throwOnError: false,
							}),
						}}
					/>
				),
			),
		[text],
	)
}
