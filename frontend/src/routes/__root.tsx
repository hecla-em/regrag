import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { createRootRoute, Outlet } from "@tanstack/react-router"
import { GlobalError } from "@/components/shared/errors/global-error"
import { NotFound } from "@/components/shared/errors/not-found"
import { TooltipProvider } from "@/components/ui/tooltip"

export const queryClient = new QueryClient()

export const Route = createRootRoute({
	component: RootLayout,
	notFoundComponent: NotFound,
	errorComponent: GlobalError,
})

function RootLayout() {
	return (
		<QueryClientProvider client={queryClient}>
			<TooltipProvider>
				<Outlet />
			</TooltipProvider>
		</QueryClientProvider>
	)
}
