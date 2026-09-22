import { defineConfig, devices } from "@playwright/test"

const isCI = Boolean(process.env.CI)

export default defineConfig({
	testDir: "e2e",
	fullyParallel: true,
	forbidOnly: isCI,
	retries: isCI ? 1 : 0,
	reporter: isCI ? [["github"], ["html", { open: "never" }]] : "list",
	use: { baseURL: "http://localhost:5173", trace: "on-first-retry" },
	projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
	webServer: [
		{
			command: "uv run python -m tests.e2e.server",
			cwd: "../backend",
			url: "http://localhost:8000/health",
			timeout: 120_000,
		},
		{
			command:
				"pnpm exec vite build && pnpm exec vite preview --port 5173 --strictPort",
			url: "http://localhost:5173",
			env: {
				VITE_API_URL: "http://localhost:8000",
				VITE_SITE_URL: "http://localhost:5173",
				VITE_SENTRY_DSN: "",
				VITE_TURNSTILE_SITE_KEY: "",
				VITE_UMAMI_WEBSITE_ID: "",
				SENTRY_AUTH_TOKEN: "",
			},
			timeout: 120_000,
		},
	],
})
