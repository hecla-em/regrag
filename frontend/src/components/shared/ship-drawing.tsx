import shipUrl from "@/assets/ship.svg"
import { cn } from "@/lib/utils"
import { MaskedSvg } from "./masked-svg"

/** A container ship line drawing, in the current text colour. */
export function ShipDrawing({ className }: { className?: string }) {
	return (
		<MaskedSvg url={shipUrl} className={cn("aspect-[4776/3834]", className)} />
	)
}
