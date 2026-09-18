import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react"
import type { Plugin } from "vite"
import { defineConfig } from "vitest/config"

/** Fails a production build that has no API URL, which would otherwise ship calling the visitor's own localhost. */
function requireApiUrl(): Plugin {
	return {
		name: "require-api-url",
		apply: "build",
		configResolved(config) {
			if (config.mode === "production" && !config.env.VITE_API_URL) {
				throw new Error("VITE_API_URL must be set for a production build")
			}
		},
	}
}

export default defineConfig({
	plugins: [
		tanstackRouter({ target: "react", autoCodeSplitting: true }),
		react(),
		tailwindcss(),
		requireApiUrl(),
	],
	resolve: {
		alias: { "@": path.resolve(__dirname, "./src") },
	},
	test: {
		include: ["src/lib/**/*.test.ts"],
	},
})
