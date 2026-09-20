import * as Sentry from "@sentry/react"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { routeTree } from "./routeTree.gen"
import "./index.css"

if (import.meta.env.VITE_SENTRY_DSN) {
	Sentry.init({
		dsn: import.meta.env.VITE_SENTRY_DSN,
		environment: import.meta.env.MODE,
		enabled: import.meta.env.PROD,
	})
}

const router = createRouter({ routeTree })

declare module "@tanstack/react-router" {
	interface Register {
		router: typeof router
	}
}

// The root route's errorComponent catches render errors, so they are reported from
// React's own hooks: onCaughtError is the one that fires for those.
// biome-ignore lint/style/noNonNullAssertion: #root is static in index.html — fail fast if missing
createRoot(document.getElementById("root")!, {
	onUncaughtError: Sentry.reactErrorHandler(),
	onCaughtError: Sentry.reactErrorHandler(),
	onRecoverableError: Sentry.reactErrorHandler(),
}).render(
	<StrictMode>
		<RouterProvider router={router} />
	</StrictMode>,
)
