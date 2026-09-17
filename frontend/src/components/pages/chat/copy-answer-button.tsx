import { CheckIcon, CopyIcon } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import type { ChatSource } from "@/api/types"
import { renumberCitations } from "@/lib/citations"

const COPIED_MS = 2000

/** Copies a settled answer out with its citations numbered as the reader saw them. */
export function CopyAnswerButton({
	answer,
	sources,
}: {
	answer: string
	sources: ChatSource[]
}) {
	const text = useMemo(
		() => renumberCitations(answer, sources),
		[answer, sources],
	)
	const [copied, setCopied] = useState(false)
	const clearing = useRef<ReturnType<typeof setTimeout> | null>(null)

	useEffect(() => {
		return () => {
			if (clearing.current !== null) clearTimeout(clearing.current)
		}
	}, [])

	/** Silent where the clipboard is out of reach, since it needs a secure context. */
	async function copyAnswer() {
		try {
			await navigator.clipboard.writeText(text)
		} catch {
			return
		}
		if (clearing.current !== null) clearTimeout(clearing.current)
		setCopied(true)
		clearing.current = setTimeout(() => setCopied(false), COPIED_MS)
	}

	return (
		<button
			type="button"
			aria-label={copied ? "Answer copied" : "Copy answer"}
			onClick={copyAnswer}
			className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
		>
			{copied ? <CheckIcon size={15} /> : <CopyIcon size={15} />}
		</button>
	)
}
