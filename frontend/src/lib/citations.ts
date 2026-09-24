import type { Element, Root, Text } from "hast"
import { visit } from "unist-util-visit"
import type { ChatSource } from "@/api/types"

const MARKER_PATTERN = /\[(\d+)\]/g
const MARKER_RUN_BEFORE_PUNCTUATION = / ?((?:\[\d+\])+)([.,;:])/g
const MARKER_RUN = / ?(?:\[\d+\]){2,}/g
const FENCE_LINE = /^ {0,3}(`{3,}|~{3,})/
const INLINE_CODE_OR_FORMULA = /(`+)(?:[\s\S]*?\1|[\s\S]*$)|\$\$[\s\S]+?\$\$/g

/** Superscripts follow punctuation: `claim [1][2].` becomes `claim.[1][2]`. */
export function moveMarkersAfterPunctuation(
	value: string,
	known: ReadonlySet<number>,
): string {
	return value.replace(
		MARKER_RUN_BEFORE_PUNCTUATION,
		(whole: string, run: string, punctuation: string) => {
			const allKnown = [...run.matchAll(MARKER_PATTERN)].every((match) =>
				known.has(Number(match[1])),
			)
			return allKnown ? `${punctuation}${run}` : whole
		},
	)
}

/**
 * A run of markers names the whole source list rather than the claim it follows, which the
 * list below the answer says better. Only markers standing on their own are shown.
 */
export function dropCitationRuns(
	value: string,
	known: ReadonlySet<number>,
): string {
	return value.replace(MARKER_RUN, (run: string) => {
		const allKnown = [...run.matchAll(MARKER_PATTERN)].every((match) =>
			known.has(Number(match[1])),
		)
		return allKnown ? "" : run
	})
}

export type CitationSegment =
	| { kind: "text"; value: string }
	| { kind: "marker"; marker: number }

export function splitCitationMarkers(
	raw: string,
	known: ReadonlySet<number>,
): CitationSegment[] {
	const value = dropCitationRuns(moveMarkersAfterPunctuation(raw, known), known)
	const segments: CitationSegment[] = []
	let cursor = 0
	for (const match of value.matchAll(MARKER_PATTERN)) {
		const marker = Number(match[1])
		if (!known.has(marker)) continue
		if (match.index > cursor) {
			segments.push({ kind: "text", value: value.slice(cursor, match.index) })
		}
		segments.push({ kind: "marker", marker })
		cursor = match.index + match[0].length
	}
	if (cursor < value.length) {
		segments.push({ kind: "text", value: value.slice(cursor) })
	}
	return segments
}

type MarkdownSegment = { code: boolean; value: string }

function splitInlineCode(value: string): MarkdownSegment[] {
	const segments: MarkdownSegment[] = []
	let cursor = 0
	for (const match of value.matchAll(INLINE_CODE_OR_FORMULA)) {
		if (match.index > cursor) {
			segments.push({ code: false, value: value.slice(cursor, match.index) })
		}
		segments.push({ code: true, value: match[0] })
		cursor = match.index + match[0].length
	}
	if (cursor < value.length) {
		segments.push({ code: false, value: value.slice(cursor) })
	}
	return segments
}

/**
 * The answer split into its code — fenced blocks, inline spans and `$$` formulas — and the
 * prose around it, so markers inside code are neither read as citations nor rewritten.
 * Mirrors the `code` parent that `rehypeCitationMarkers` skips, and rejoins to exactly what
 * it was given.
 */
function splitMarkdownCode(markdown: string): MarkdownSegment[] {
	const segments: MarkdownSegment[] = []
	const lines = markdown.split("\n")
	let prose = ""
	let fence: string | null = null
	lines.forEach((line, index) => {
		const value = index === lines.length - 1 ? line : `${line}\n`
		const delimiter = line.match(FENCE_LINE)?.[1]
		if (fence !== null) {
			segments.push({ code: true, value })
			if (delimiter?.[0] === fence[0] && delimiter.length >= fence.length) {
				fence = null
			}
			return
		}
		if (delimiter === undefined) {
			prose += value
			return
		}
		segments.push(...splitInlineCode(prose), { code: true, value })
		prose = ""
		fence = delimiter
	})
	return [...segments, ...splitInlineCode(prose)]
}

function removeMarkdownCode(markdown: string): string {
	return splitMarkdownCode(markdown)
		.filter((segment) => !segment.code)
		.map((segment) => segment.value)
		.join("")
}

/** Markers the answer cites, once each, in order of first appearance. */
export function extractCitedMarkers(
	answer: string,
	known: ReadonlySet<number>,
): number[] {
	const cited = new Set<number>()
	for (const match of removeMarkdownCode(answer).matchAll(MARKER_PATTERN)) {
		const marker = Number(match[1])
		if (known.has(marker)) cited.add(marker)
	}
	return [...cited]
}

/**
 * Display number for each cited marker: 1..k by first appearance.
 * Markers are retrieval positions, so an answer citing [7] and [12] reads as 1 and 2.
 */
export function numberCitations(
	answer: string,
	known: ReadonlySet<number>,
): ReadonlyMap<number, number> {
	const cited = extractCitedMarkers(answer, known)
	return new Map(cited.map((marker, index) => [marker, index + 1]))
}

function toHastNode(segment: CitationSegment): Text | Element {
	if (segment.kind === "text") return { type: "text", value: segment.value }
	return {
		type: "element",
		tagName: "cite-marker",
		properties: { marker: String(segment.marker) },
		children: [],
	}
}

/** Whether splitting changed the text, by marking a citation or by taking a run away. */
function isRewritten(segments: CitationSegment[], value: string): boolean {
	const text = segments
		.map((segment) => (segment.kind === "text" ? segment.value : ""))
		.join("")
	return segments.some((segment) => segment.kind === "marker") || text !== value
}

export function rehypeCitationMarkers(known: ReadonlySet<number>) {
	return () => (tree: Root) => {
		visit(tree, "text", (node: Text, index, parent) => {
			if (parent === undefined || index === undefined) return
			if (parent.type === "element" && parent.tagName === "code") return
			const segments = splitCitationMarkers(node.value, known)
			if (!isRewritten(segments, node.value)) return
			parent.children.splice(index, 1, ...segments.map(toHastNode))
			return index + segments.length
		})
	}
}

export type CitedSource = { source: ChatSource; label: number }

/** The sources an answer cites, in the order its markers first appear. */
export function citedSources(
	answer: string,
	sources: ChatSource[],
): CitedSource[] {
	const byMarker = new Map(sources.map((source) => [source.marker, source]))
	const numbers = numberCitations(answer, new Set(byMarker.keys()))
	return [...numbers].flatMap(([marker, label]) => {
		const source = byMarker.get(marker)
		return source === undefined ? [] : [{ source, label }]
	})
}

/** The answer with its markers rewritten as the numbers the reader saw, for copying out. */
export function renumberCitations(
	answer: string,
	sources: ChatSource[],
): string {
	const known = new Set(sources.map((source) => source.marker))
	const numbers = numberCitations(answer, known)
	return splitMarkdownCode(answer)
		.map((segment) =>
			segment.code
				? segment.value
				: dropCitationRuns(segment.value, known).replace(
						MARKER_PATTERN,
						(whole: string, marker: string) => {
							const label = numbers.get(Number(marker))
							return label === undefined ? whole : `[${label}]`
						},
					),
		)
		.join("")
}
