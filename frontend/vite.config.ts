import path from "node:path"
import { sentryVitePlugin } from "@sentry/vite-plugin"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

export default defineConfig(({ mode }) => {
	const sentryAuthToken = process.env.SENTRY_AUTH_TOKEN
	const enableSentry = mode === "production" && Boolean(sentryAuthToken)

	return {
		plugins: [
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
