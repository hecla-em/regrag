import type { Element, Root } from "hast"
import { describe, expect, it } from "vitest"
import type { ChatSource } from "@/api/types"
import {
	citedSources,
	dropCitationRuns,
	extractCitedMarkers,
	moveMarkersAfterPunctuation,
	rehypeCitationMarkers,
	renumberCitations,
} from "./citations"

const known = new Set([1, 2, 7, 12])

it.each([
	[
		"moves a marker past the punctuation it precedes",
		"claim [1].",
		"claim.[1]",
	],
	["keeps a run of markers together", "claim [1][2].", "claim.[1][2]"],
	["moves a marker not preceded by a space", "claim[1],", "claim,[1]"],
	[
		"handles every punctuation mark it recognises",
		"a [1]. b [1], c [1]; d [1]:",
		"a.[1] b,[1] c;[1] d:[1]",
	],
	[
		"leaves a run alone when any marker is unknown",
		"claim [1][9].",
		"claim [1][9].",
	],
	[
		"leaves markers alone when no punctuation follows",
		"claim [1] and more",
		"claim [1] and more",
	],
])("moveMarkersAfterPunctuation %s", (_rule, text, expected) => {
	expect(moveMarkersAfterPunctuation(text, known)).toBe(expected)
})

it.each([
	[
		"returns known markers in order of first appearance",
		"[7] then [2] then [12]",
		[7, 2, 12],
	],
	["reports a repeated marker once", "[2] and [1] and [2]", [2, 1]],
	["ignores markers outside the known set", "[9] and [1]", [1]],
	["ignores markers inside inline code", "read `arr[1]` then cite [7]", [7]],
	[
		"ignores markers inside a fenced block",
		"cite [7]\n```ts\nconst x = arr[1]\n```\nend",
		[7],
	],
	["ignores markers inside a tilde fence", "cite [7]\n~~~\narr[1]\n~~~", [7]],
	[
		"ignores markers inside a fence that is still streaming",
		"cite [7]\n```ts\nconst x = arr[1]",
		[7],
	],
	[
		"keeps markers that share a line with inline code",
		"`arr[1]` supports [2]",
		[2],
	],
])("extractCitedMarkers %s", (_rule, text, expected) => {
	expect(extractCitedMarkers(text, known)).toEqual(expected)
})

it.each([
	[
		"drops a run of markers",
		"Exemptions expire in 2029.[1][2][7]",
		"Exemptions expire in 2029.",
	],
	[
		"keeps a marker that stands alone",
		"Island routes are exempt.[2]",
		"Island routes are exempt.[2]",
	],
	[
		"takes the space a run was separated by",
		"a claim [1][2] and more",
		"a claim and more",
	],
	[
		"leaves a run alone when any marker is unknown",
		"claim [1][9]",
		"claim [1][9]",
	],
])("dropCitationRuns %s", (_rule, text, expected) => {
	expect(dropCitationRuns(text, known)).toBe(expected)
})

function paragraph(...values: string[]): Root {
	return {
		type: "root",
		children: [
			{
				type: "element",
				tagName: "p",
				properties: {},
				children: values.map((value) => ({ type: "text", value })),
			},
		],
	}
}

function firstChild(tree: Root): Element {
	return tree.children[0] as Element
}

const citeMarker = (marker: string) => ({
	type: "element",
	tagName: "cite-marker",
	properties: { marker },
	children: [],
})

describe("rehypeCitationMarkers", () => {
	it.each([
		[
			"replaces known markers with cite-marker elements",
			"claim [1].",
			[{ type: "text", value: "claim." }, citeMarker("1")],
		],
		[
			"takes away a run even where no marker survives it",
			"claim [1][2].",
			[{ type: "text", value: "claim." }],
		],
		[
			"leaves text without known markers untouched",
			"claim [9].",
			[{ type: "text", value: "claim [9]." }],
		],
	])("%s", (_rule, text, expected) => {
		const tree = paragraph(text)
		rehypeCitationMarkers(known)()(tree)
		expect(firstChild(tree).children).toEqual(expected)
	})

	it("skips markers inside code elements", () => {
		const tree: Root = {
			type: "root",
			children: [
				{
					type: "element",
					tagName: "code",
					properties: {},
					children: [{ type: "text", value: "arr[1]" }],
				},
			],
		}
		rehypeCitationMarkers(known)()(tree)
		expect(firstChild(tree).children).toEqual([
			{ type: "text", value: "arr[1]" },
		])
	})

	it("rewrites every text node in a paragraph", () => {
		const tree = paragraph("first [1].", " second [2].")
		rehypeCitationMarkers(known)()(tree)
		expect(
			firstChild(tree).children.filter(
				(child) => child.type === "element" && child.tagName === "cite-marker",
			),
		).toHaveLength(2)
	})
})

function source(marker: number): ChatSource {
	return {
		marker,
		name: "Regulation (EU) 2023/1805",
		url: "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R1805",
		site: "EUR-Lex",
		citation: "Article 4(1)",
		title: "Greenhouse gas intensity limit",
		text: "The limit applies from 2025.",
	}
}

const sources = [source(1), source(7), source(12)]

it.each([
	[
		"returns the cited sources with the number the answer shows",
		"claim [7] and [12].",
		[
			{ source: sources[1], label: 1 },
			{ source: sources[2], label: 2 },
		],
	],
	[
		"leaves out a retrieved source the answer never cites",
		"claim [7].",
		[{ source: sources[1], label: 1 }],
	],
	["is empty when the answer cites nothing", "claim.", []],
	[
		"keeps a source the answer only cites inside a run",
		"claim [7]. All of it [7][12].",
		[
			{ source: sources[1], label: 1 },
			{ source: sources[2], label: 2 },
		],
	],
])("citedSources %s", (_rule, answer, expected) => {
	expect(citedSources(answer, sources)).toEqual(expected)
})

it.each([
	[
		"rewrites markers as the numbers the reader saw",
		"claim [7] and [12].",
		"claim [1] and [2].",
	],
	[
		"gives a repeated marker the same number each time",
		"claim [7], again [7].",
		"claim [1], again [1].",
	],
	[
		"leaves a marker that was never retrieved alone",
		"claim [9].",
		"claim [9].",
	],
	[
		"gives back an answer it has nothing to rewrite, exactly",
		"A limit.\n\n```ts\nconst x = 1\n```\n\n- a `span` and text\n",
		"A limit.\n\n```ts\nconst x = 1\n```\n\n- a `span` and text\n",
	],
	[
		"leaves markers inside inline code exactly as they were",
		"read `values[7][12]` then cite [7].",
		"read `values[7][12]` then cite [1].",
	],
	[
		"leaves markers inside a fenced block alone",
		"cite [7].\n```ts\nconst x = values[7][12]\n```",
		"cite [1].\n```ts\nconst x = values[7][12]\n```",
	],
	[
		"drops the runs the answer does not show",
		"claim [7]. All of it [7][12].",
		"claim [1]. All of it.",
	],
])("renumberCitations %s", (_rule, answer, expected) => {
	expect(renumberCitations(answer, sources)).toBe(expected)
})
