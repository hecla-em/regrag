import { CheckIcon, ChevronDownIcon } from "lucide-react"
import { memo, useEffect, useState } from "react"
import { ThinkingOrb } from "thinking-orbs"
import type { ChatStep } from "@/api/types"
import { Button } from "@/components/ui/button"
import {
	Popover,
	PopoverContent,
	PopoverTrigger,
} from "@/components/ui/popover"
import { formatMs, stepLabel } from "@/lib/chat-steps"
import { cn } from "@/lib/utils"

const ELAPSED_TICK_MS = 100

function useElapsedMs(since: number, isRunning: boolean): number {
	const [now, setNow] = useState(Date.now)
	useEffect(() => {
		if (!isRunning) return
		const timer = setInterval(() => setNow(Date.now()), ELAPSED_TICK_MS)
		return () => clearInterval(timer)
	}, [isRunning])
	return Math.max(0, now - since)
}

function SolvingOrb() {
	return <ThinkingOrb state="solving" size={20} theme="dark" />
}

function StepRow({ step }: { step: ChatStep }) {
	const isDone = step.status === "completed"
	return (
		<li
			className={cn(
				"grid grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-2 rounded-lg px-2 py-1",
				!isDone && "bg-secondary",
			)}
		>
			{isDone ? (
				<CheckIcon
					size={14}
					strokeWidth={2.5}
					className="justify-self-center text-success"
					aria-hidden
				/>
			) : (
				<SolvingOrb />
			)}
			<span className="truncate">
				{stepLabel(step)}
				{step.subject && (
					<span className="ml-1.5 text-faint-foreground">{step.subject}</span>
				)}
			</span>
			<span className="text-[10.5px] text-faint-foreground tabular-nums">
				{isDone && formatMs(step.ms)}
			</span>
		</li>
	)
}

function ChipLabel({
	steps,
	isRunning,
	askedAt,
	endedAt,
}: {
	steps: ChatStep[]
	isRunning: boolean
	askedAt: number
	endedAt: number | null
}) {
	const elapsedMs = useElapsedMs(askedAt, isRunning)
	if (!isRunning) {
		return (
			<>
				<span aria-hidden className="mx-1.5 size-1.5 rounded-full bg-success" />
				<span role="status">
					{steps.length} {steps.length === 1 ? "step" : "steps"} ·{" "}
					{formatMs((endedAt ?? askedAt) - askedAt)}
				</span>
				<ChevronDownIcon
					size={12}
					className="transition-transform duration-200 group-data-popup-open:rotate-180"
					aria-hidden
				/>
			</>
		)
	}
	const current = steps.findLast((step) => step.status === "running")
	return (
		<>
			<SolvingOrb />
			<span role="status" className="shimmer-text truncate">
				{current ? stepLabel(current) : "Working"}…
			</span>
			<span className="shrink-0 text-faint-foreground">
				· {formatMs(elapsedMs)}
			</span>
		</>
	)
}

/** The path a run took, as a chip above its answer: the step it is on while it runs, and the
 * whole trail in a popover that opens over the answer without moving it. */
export const RunSteps = memo(function RunSteps({
	steps,
	isRunning,
	askedAt,
	endedAt,
}: {
	steps: ChatStep[]
	isRunning: boolean
	askedAt: number
	endedAt: number | null
}) {
	if (steps.length === 0 && !isRunning) return null

	return (
		<Popover>
			<PopoverTrigger
				render={<Button variant="outline" size="sm" />}
				className="group h-7 w-fit max-w-full gap-1.5 self-start rounded-lg bg-card pr-2.5 pl-1 font-mono font-normal text-muted-foreground text-xs tabular-nums dark:bg-card"
			>
				<ChipLabel
					steps={steps}
					isRunning={isRunning}
					askedAt={askedAt}
					endedAt={endedAt}
				/>
			</PopoverTrigger>
			<PopoverContent
				align="start"
				className="w-75 max-w-[calc(100vw-2rem)] gap-0 rounded-2xl p-1.5 font-mono text-xs ring-border"
			>
				<ol className="flex flex-col">
					{steps.map((step, index) => (
						// biome-ignore lint/suspicious/noArrayIndexKey: the trail only grows at its end, so a step's position is its identity
						<StepRow key={index} step={step} />
					))}
				</ol>
				{steps.length === 0 && (
					<p className="flex items-center gap-2 px-2 py-1">
						<SolvingOrb />
						Working…
					</p>
				)}
			</PopoverContent>
		</Popover>
	)
})
