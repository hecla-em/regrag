import shipUrl from "@/assets/ship.svg"
import { cn } from "@/lib/utils"

const SHIP_MASK = `url("${shipUrl}") center / contain no-repeat`

/** A container ship line drawing, painted in the current text colour through a mask. */
export function ShipDrawing({ className }: { className?: string }) {
	return (
		<span
			aria-hidden="true"
			className={cn("inline-block aspect-[4776/3834] bg-current", className)}
			style={{ WebkitMask: SHIP_MASK, mask: SHIP_MASK }}
		/>
	)
}
