import { ArrowUpIcon, SquareIcon } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

/** Kept short enough to sit on one line in the composer. Each names its act, as the corpus holds several. */
const SAMPLE_QUESTIONS = [
	"What is the greenhouse gas intensity limit under FuelEU Maritime?",
	"Which ships fall outside the scope of FuelEU Maritime?",
	"How is a ship's compliance balance calculated under FuelEU Maritime?",
	"What is the FuelEU Maritime penalty for a compliance deficit?",
	"When must ships use onshore power supply under FuelEU Maritime?",
	"Which ships must report CO2 emissions under the MRV Regulation?",
	"What must a monitoring plan contain under the MRV Regulation?",
	"How much of a ship's emissions must be covered by EU ETS allowances?",
	"Which authority administers a shipping company under the EU ETS?",
]

function pickSampleQuestion(): string {
	return SAMPLE_QUESTIONS[Math.floor(Math.random() * SAMPLE_QUESTIONS.length)]
}

export function PromptForm({
	isBusy,
	onSubmit,
	onStop,
}: {
	isBusy: boolean
	onSubmit: (question: string) => void
	onStop: () => void
}) {
	const [question, setQuestion] = useState("")
	const [suggestion, setSuggestion] = useState<string | null>(
		pickSampleQuestion,
	)
	const visibleSuggestion = question === "" ? suggestion : null

	/** The suggestion goes for good once the reader writes their own question, or takes it with →. */
	function typeQuestion(value: string) {
		setQuestion(value)
		if (value !== "") setSuggestion(null)
	}

	function submitQuestion(event: { preventDefault: () => void }) {
		event.preventDefault()
		const submitted = question.trim()
		if (submitted === "") return
		setQuestion("")
		onSubmit(submitted)
	}

	return (
		<form
			onSubmit={submitQuestion}
			className="flex items-center gap-2 rounded-[20px] border bg-card py-2 pr-2 pl-4 shadow-lg shadow-black/35"
		>
			<Textarea
				value={question}
				onChange={(event) => typeQuestion(event.target.value)}
				onKeyDown={(event) => {
					if (event.key === "ArrowRight" && visibleSuggestion !== null) {
						event.preventDefault()
						typeQuestion(visibleSuggestion)
						return
					}
					if (isBusy) return
					if (event.key === "Enter" && !event.shiftKey) submitQuestion(event)
				}}
				placeholder={suggestion ?? "Ask a question…"}
				aria-label="Ask a question"
				rows={1}
				className="min-h-9 flex-1 resize-none border-0 bg-transparent px-1 text-sm focus-visible:ring-0"
			/>
			{isBusy ? (
				<Button
					type="button"
					size="icon-lg"
					className="rounded-xl"
					aria-label="Stop"
					onClick={onStop}
				>
					<SquareIcon />
				</Button>
			) : (
				<Button
					type="submit"
					size="icon-lg"
					className="rounded-xl"
					aria-label="Send"
					disabled={question.trim() === ""}
				>
					<ArrowUpIcon />
				</Button>
			)}
		</form>
	)
}
