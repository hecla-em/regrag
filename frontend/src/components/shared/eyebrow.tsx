import type * as React from "react"
import { cn } from "@/lib/utils"

export const EYEBROW =
	"font-mono text-[10.5px] text-faint-foreground uppercase tracking-[0.12em]"

/** A small monospace caps label over a group. */
export function Eyebrow({ className, ...props }: React.ComponentProps<"h2">) {
	return <h2 className={cn(EYEBROW, className)} {...props} />
}
