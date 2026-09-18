import { CheckIcon, CopyIcon } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import type { ChatSource } from "@/api/types"
import { Button } from "@/components/ui/button"
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
		<Button
			variant="ghost"
			size="icon-xs"
			aria-label={copied ? "Answer copied" : "Copy answer"}
			onClick={copyAnswer}
			className="rounded-md text-muted-foreground"
		>
			{copied ? (
				<CheckIcon className="size-3.75" />
			) : (
				<CopyIcon className="size-3.75" />
			)}
		</Button>
	)
}
