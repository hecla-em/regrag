import { CheckIcon, CopyIcon } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import type { ChatSource } from "@/api/types"
import { renumberCitations } from "@/lib/citations"

const COPIED_MS = 2000

function CopyAnswerButton({ text }: { text: string }) {
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

/** What a reader can do with a settled answer: copy it out with the citations numbered as shown. */
export function AnswerActions({
	answer,
	sources,
}: {
	answer: string
	sources: ChatSource[]
}) {
	const copyText = useMemo(
		() => renumberCitations(answer, sources),
		[answer, sources],
	)

	return (
		<div className="fade-in -mx-1 flex animate-in items-center duration-300">
			<CopyAnswerButton text={copyText} />
		</div>
	)
}
