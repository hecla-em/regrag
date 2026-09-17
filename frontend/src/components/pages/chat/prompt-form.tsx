import { ArrowUpIcon, SquareIcon } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

const SAMPLE_QUESTIONS = [
	"What is the greenhouse gas intensity limit under FuelEU Maritime?",
	"When must a company monitor energy used on board?",
	"Which ships fall outside the scope of the regulation?",
	"How is the compliance balance of a ship calculated?",
	"What are the penalties for a compliance deficit?",
	"When must ships use onshore power supply at berth?",
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
	const [isFocused, setIsFocused] = useState(false)
	const [suggestion, setSuggestion] = useState<string | null>(
		pickSampleQuestion,
	)
	const visibleSuggestion = !isFocused && question === "" ? suggestion : null

	function submitQuestion(event: { preventDefault: () => void }) {
		event.preventDefault()
		const trimmed = question.trim()
		const submitted = trimmed !== "" ? trimmed : visibleSuggestion
		if (submitted === null || submitted === "") return
		setQuestion("")
		setSuggestion(null)
		onSubmit(submitted)
	}

	return (
		<form
			onSubmit={submitQuestion}
			className="flex items-center gap-2 rounded-[20px] border bg-card py-2 pr-2 pl-4 shadow-lg shadow-black/35"
		>
			<Textarea
				value={question}
				onChange={(event) => setQuestion(event.target.value)}
				onFocus={() => setIsFocused(true)}
				onBlur={() => setIsFocused(false)}
				onKeyDown={(event) => {
					if (isBusy) return
					if (event.key === "Enter" && !event.shiftKey) submitQuestion(event)
				}}
				placeholder={
					visibleSuggestion ?? (suggestion === null ? "Ask a question…" : "")
				}
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
					onMouseDown={(event) => event.preventDefault()}
				>
					<ArrowUpIcon />
				</Button>
			)}
		</form>
	)
}
