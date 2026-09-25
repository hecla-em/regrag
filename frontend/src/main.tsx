import * as Sentry from "@sentry/react"
import { createRouter, RouterProvider } from "@tanstack/react-router"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { prepareToken } from "@/lib/turnstile"
import { routeTree } from "./routeTree.gen"
import "./index.css"

if (import.meta.env.VITE_SENTRY_DSN) {
	Sentry.init({
		dsn: import.meta.env.VITE_SENTRY_DSN,
		environment: import.meta.env.MODE,
		enabled: import.meta.env.PROD,
	})
}

if (import.meta.env.VITE_UMAMI_WEBSITE_ID) {
	const umami = document.createElement("script")
	umami.src = "https://analytics.hecla-em.com/script.js"
	umami.defer = true
	umami.dataset.websiteId = import.meta.env.VITE_UMAMI_WEBSITE_ID
	umami.dataset.domains = "ask.hecla-em.com"
	document.head.appendChild(umami)
}

prepareToken()

const router = createRouter({ routeTree })

declare module "@tanstack/react-router" {
	interface Register {
		router: typeof router
	}
}

// The root route's errorComponent catches render errors, so they are reported from
// React's own hooks: onCaughtError is the one that fires for those. Setting a hook drops
// React's own console line for it, so the callback writes it back.
const reportRenderError = Sentry.reactErrorHandler((error, errorInfo) => {
	console.error(error, errorInfo.componentStack)
})

// biome-ignore lint/style/noNonNullAssertion: #root is static in index.html — fail fast if missing
createRoot(document.getElementById("root")!, {
	onUncaughtError: reportRenderError,
	onCaughtError: reportRenderError,
	onRecoverableError: reportRenderError,
}).render(
	<StrictMode>
		<RouterProvider router={router} />
	</StrictMode>,
)
