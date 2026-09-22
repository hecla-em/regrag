import { ThumbsDownIcon, ThumbsUpIcon } from "lucide-react"
import type { Vote } from "@/api/types"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const THUMBS: { vote: Vote; label: string; Icon: typeof ThumbsUpIcon }[] = [
	{ vote: "up", label: "Good answer", Icon: ThumbsUpIcon },
	{ vote: "down", label: "Poor answer", Icon: ThumbsDownIcon },
]

/** The reader's vote on a settled answer: the chosen thumb stays filled, a second click on
 * it takes the vote back, and the other thumb swaps it. */
export function VoteButtons({
	vote,
	onVote,
}: {
	vote: Vote | null
	onVote: (vote: Vote | null) => void
}) {
	return (
		<>
			{THUMBS.map(({ vote: thumb, label, Icon }) => {
				const chosen = vote === thumb
				return (
					<Button
						key={thumb}
						variant="ghost"
						size="icon-xs"
						aria-label={label}
						aria-pressed={chosen}
						onClick={() => onVote(chosen ? null : thumb)}
						className={cn(
							"rounded-md text-muted-foreground",
							chosen && "text-foreground",
						)}
					>
						<Icon className={cn("size-3.75", chosen && "fill-current")} />
					</Button>
				)
			})}
		</>
	)
}
