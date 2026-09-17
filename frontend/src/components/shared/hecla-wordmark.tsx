import wordmarkUrl from "@/assets/hecla-wordmark.svg"
import { cn } from "@/lib/utils"

const WORDMARK_MASK = `url("${wordmarkUrl}") center / contain no-repeat`

/** The HECLA wordmark, painted in the current text colour through a mask. */
export function HeclaWordmark({ className }: { className?: string }) {
	return (
		<span
			role="img"
			aria-label="Hecla"
			className={cn("inline-block aspect-[3200/760] bg-current", className)}
			style={{ WebkitMask: WORDMARK_MASK, mask: WORDMARK_MASK }}
		/>
	)
}
