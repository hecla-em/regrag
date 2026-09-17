import { Collapsible } from "@base-ui/react/collapsible"
import { CheckIcon, ChevronDownIcon } from "lucide-react"
import { memo, useState } from "react"
import { ThinkingOrb } from "thinking-orbs"
import type { ChatStep } from "@/api/types"
import { formatDuration, stepLabel } from "@/lib/chat-steps"
import { cn } from "@/lib/utils"

function StepIcon({ step, isRunning }: { step: ChatStep; isRunning: boolean }) {
	if (step.status === "completed") {
		return (
			<CheckIcon
				size={14}
				strokeWidth={2.5}
				className="shrink-0 text-muted-foreground"
				aria-hidden
			/>
		)
	}
	return (
		<span
			aria-hidden
			className={cn(
				"size-3 shrink-0 rounded-full border-[1.5px] border-border",
				isRunning && "animate-spin border-t-muted-foreground",
			)}
		/>
	)
}

/** The path a run took, above the answer it produced: the step it is on while it runs, and a
 * record of how the answer was reached once it settles. Open while running unless the reader
 * has chosen otherwise. */
export const RunSteps = memo(function RunSteps({
	steps,
	isRunning,
}: {
	steps: ChatStep[]
	isRunning: boolean
}) {
	const [openedByReader, setOpenedByReader] = useState<boolean | null>(null)
	const isOpen = openedByReader ?? isRunning

	if (steps.length === 0 && !isRunning) return null

	return (
		<Collapsible.Root
			open={isOpen}
			onOpenChange={setOpenedByReader}
			className="flex w-full flex-col"
		>
			<Collapsible.Trigger className="group -mx-1.5 flex w-fit items-center gap-2 rounded-md px-1.5 py-1 transition-colors hover:bg-muted">
				{isRunning ? (
					<ThinkingOrb state="solving" size={20} theme="dark" />
				) : (
					<span aria-hidden className="flex size-5 items-center justify-center">
						<span className="size-2 rounded-full bg-muted-foreground" />
					</span>
				)}
				<span
					role="status"
					className={cn(
						"text-xs whitespace-nowrap",
						isRunning
							? "shimmer-text"
							: "fade-in animate-in text-muted-foreground duration-300",
					)}
				>
					{isRunning
						? "Working"
						: `${steps.length} ${steps.length === 1 ? "step" : "steps"} · ${formatDuration(steps)}`}
				</span>
				<ChevronDownIcon
					size={14}
					className="text-muted-foreground transition-transform duration-300 group-data-panel-open:rotate-180"
					aria-hidden
				/>
			</Collapsible.Trigger>

			<Collapsible.Panel className="h-(--collapsible-panel-height) overflow-hidden transition-[height,opacity] duration-400 ease-[cubic-bezier(0.23,1,0.32,1)] data-ending-style:h-0 data-ending-style:opacity-0 data-starting-style:h-0 data-starting-style:opacity-0">
				<div className="relative mt-1 ml-[5px] pl-4">
					<span
						aria-hidden
						className="-top-2 absolute bottom-2.5 left-[3px] w-px bg-border"
					/>
					<ol className="flex flex-col gap-1 py-1">
						{steps.map((step, index) => (
							<li
								// biome-ignore lint/suspicious/noArrayIndexKey: the trail only grows at its end, so a step's position is its identity
								key={index}
								className="fade-in slide-in-from-bottom-1 flex min-h-7 w-full animate-in items-center gap-2 fill-mode-both px-1.5 py-0.5 duration-300"
							>
								<StepIcon step={step} isRunning={isRunning} />
								<span className="min-w-0 truncate font-medium text-xs">
									{stepLabel(step)}
								</span>
								{step.subject && (
									<span className="min-w-0 truncate text-muted-foreground text-xs">
										{step.subject}
									</span>
								)}
							</li>
						))}
					</ol>
				</div>
			</Collapsible.Panel>
		</Collapsible.Root>
	)
})
