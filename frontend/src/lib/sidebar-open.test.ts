import { describe, expect, it } from "vitest"
import { readSidebarOpen } from "./sidebar-open"

describe("readSidebarOpen", () => {
	it("is open when no choice was kept", () => {
		expect(readSidebarOpen("")).toBe(true)
	})

	it("is closed when the sidebar was left collapsed", () => {
		expect(readSidebarOpen("theme=dark; sidebar_state=false")).toBe(false)
	})

	it("is open when the sidebar was left expanded", () => {
		expect(readSidebarOpen("sidebar_state=true; theme=dark")).toBe(true)
	})
})
