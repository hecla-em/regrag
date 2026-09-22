import type { ChatStep } from "@/api/types"

const LABELS: Record<ChatStep["step"], { running: string; done: string }> = {
	rewrite: { running: "Rewriting the question", done: "Rewrote the question" },
	decompose: { running: "Splitting the question", done: "Split the question" },
	retrieve: { running: "Searching the corpus", done: "Searched the corpus" },
	assess: { running: "Reviewing the evidence", done: "Reviewed the evidence" },
	assess_tools: { running: "Running tools", done: "Ran tools" },
	tool_search: { running: "Extending the search", done: "Extended the search" },
	tool_follow_reference: {
		running: "Following a reference",
		done: "Followed a reference",
	},
	tool_mrv_figures: {
		running: "Reading the THETIS-MRV figures",
		done: "Read the THETIS-MRV figures",
	},
	tool_refuse: {
		running: "Finding nothing that bears on the question",
		done: "Found nothing that bears on the question",
	},
	tool_unknown: {
		running: "Asking for a tool it does not have",
		done: "Asked for a tool it does not have",
	},
	synthesize: { running: "Writing the answer", done: "Wrote the answer" },
	refuse: { running: "Declining to answer", done: "Declined to answer" },
}

/** What a step is called in the trail, in the tense its status calls for. A step the schema
 * has outgrown goes by its own name rather than taking the page down with it. */
export function stepLabel(step: ChatStep): string {
	const named = LABELS[step.step] ?? { running: step.step, done: step.step }
	return step.status === "running" ? named.running : named.done
}

export function formatMs(ms: number): string {
	return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}
