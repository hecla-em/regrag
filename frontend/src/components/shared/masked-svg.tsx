import { cn } from "@/lib/utils"

/** An SVG painted in the current text colour through a mask. Decorative unless given a label. */
export function MaskedSvg({
	url,
	label,
	className,
	...props
}: {
	url: string
	label?: string
} & Omit<React.ComponentProps<"span">, "children" | "style">) {
	const mask = `url("${url}") center / contain no-repeat`

	const labelling = label
		? ({ role: "img", "aria-label": label } as const)
		: ({ "aria-hidden": true } as const)

	return (
		<span
			{...labelling}
			className={cn("inline-block bg-current", className)}
			style={{ WebkitMask: mask, mask }}
			{...props}
		/>
	)
}
