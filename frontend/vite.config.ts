import path from "node:path"
import { sentryVitePlugin } from "@sentry/vite-plugin"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import type { Plugin } from "vite"
import { defineConfig } from "vitest/config"

const REQUIRED_ENV = ["VITE_API_URL", "VITE_SITE_URL"]
const DEPLOY_ENV = [
	"VITE_SENTRY_DSN",
	"VITE_TURNSTILE_SITE_KEY",
	"VITE_UMAMI_WEBSITE_ID",
	"SENTRY_AUTH_TOKEN",
]

/** Fails dev and build on a missing variable, and a Pages production build on a missing deploy one. */
function requireEnv(): Plugin {
	return {
		name: "require-env",
		configResolved({ env, mode }) {
			if (mode === "test") return
			const names =
				process.env.CF_PAGES_BRANCH === "main"
					? [...REQUIRED_ENV, ...DEPLOY_ENV]
					: REQUIRED_ENV
			const missing = names.filter((name) => !env[name] && !process.env[name])
			if (missing.length > 0) {
				throw new Error(`Missing environment variables: ${missing.join(", ")}`)
			}
		},
	}
}

export default defineConfig(({ mode }) => {
	const sentryAuthToken = process.env.SENTRY_AUTH_TOKEN
	const enableSentry = mode === "production" && Boolean(sentryAuthToken)

	return {
		plugins: [
			requireEnv(),
			tanstackRouter({ target: "react", autoCodeSplitting: true }),
			react(),
			tailwindcss(),
			// Source maps go to Sentry and are deleted from dist, so the site never serves them
			enableSentry
				? sentryVitePlugin({
						org: "callummacalisterhecla-emcom",
						project: "regrag-frontend",
						authToken: sentryAuthToken,
						sourcemaps: { filesToDeleteAfterUpload: ["./dist/**/*.map"] },
					})
				: false,
		],
		resolve: {
			alias: { "@": path.resolve(__dirname, "./src") },
		},
		build: {
			sourcemap: enableSentry ? "hidden" : false,
		},
		test: {
			include: ["src/lib/**/*.test.ts"],
		},
	}
})
