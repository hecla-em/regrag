import wordmarkUrl from "@/assets/hecla-wordmark.svg"
import { cn } from "@/lib/utils"
import { MaskedSvg } from "./masked-svg"

/** The HECLA wordmark, in the current text colour. */
export function HeclaWordmark({
	className,
	...props
}: Omit<React.ComponentProps<typeof MaskedSvg>, "url" | "label">) {
	return (
		<MaskedSvg
			url={wordmarkUrl}
			label="Hecla"
			className={cn("aspect-[3200/760]", className)}
			{...props}
		/>
	)
}
