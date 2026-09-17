import type { ErrorComponentProps } from "@tanstack/react-router"
import { Button } from "@/components/ui/button"
import { MessagePage } from "./message-page"

export function GlobalError({ error, reset }: ErrorComponentProps) {
	return (
		<MessagePage
			title="Something went wrong"
			description={
				import.meta.env.DEV && error instanceof Error
					? error.message
					: "Please try again in a moment."
			}
			action={<Button onClick={() => reset()}>Retry</Button>}
		/>
	)
}
