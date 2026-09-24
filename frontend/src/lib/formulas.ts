import type { Element, ElementContent, Root } from "hast"
import { visit } from "unist-util-visit"

const FORMULA = /\$\$([\s\S]+?)\$\$/g

export type FormulaSegment =
	| { kind: "text"; value: string }
	| { kind: "formula"; latex: string; display: boolean }

/** Whether a formula has nothing but line breaks, or the text's edge, on either side. */
function standsAlone(before: string | null, after: string | null): boolean {
	return (
		(before === null || before.endsWith("\n")) &&
		(after === null || after.startsWith("\n"))
	)
}

/** Plain text split at its `$$latex$$` formulas, a formula alone on its line set as a block
 * and the line breaks around that block dropped. */
export function splitFormulas(text: string): FormulaSegment[] {
	const parts = text.split(FORMULA)
	const display = parts.map(
		(_, index) =>
			index % 2 === 1 &&
			standsAlone(
				index === 1 && parts[0] === "" ? null : parts[index - 1],
				index === parts.length - 2 && parts[index + 1] === ""
					? null
					: parts[index + 1],
			),
	)
	return parts.flatMap((part, index): FormulaSegment[] => {
		if (index % 2 === 1) {
			return [{ kind: "formula", latex: part, display: display[index] }]
		}
		let value = part
		if (display[index - 1]) value = value.replace(/^\n/, "")
		if (display[index + 1]) value = value.replace(/\n$/, "")
		return value === "" ? [] : [{ kind: "text", value }]
	})
}

function neighbourText(node: ElementContent | undefined): string | null {
	if (node === undefined) return null
	return node.type === "text" ? node.value : ""
}

/** Marks remark-math's inline formulas that stand alone on a paragraph's line as display
 * maths, so rehype-katex sets them as blocks. */
export function rehypeDisplayFormulas() {
	return (tree: Root) => {
		visit(tree, "element", (node: Element, index, parent) => {
			const classes = node.properties.className
			if (!Array.isArray(classes) || !classes.includes("math-inline")) return
			if (parent?.type !== "element" || parent.tagName !== "p") return
			if (index === undefined) return
			const siblings = parent.children as ElementContent[]
			if (
				standsAlone(
					neighbourText(siblings[index - 1]),
					neighbourText(siblings[index + 1]),
				)
			) {
				node.properties.className = classes.map((name) =>
					name === "math-inline" ? "math-display" : name,
				)
			}
		})
	}
}
