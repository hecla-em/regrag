import { describe, expect, it } from "vitest"
import {
	readSidebarCollapsed,
	storeSidebarCollapsed,
} from "./sidebar-collapsed"

function storage() {
	const held = new Map<string, string>()
	return () => ({
		getItem: (key: string) => held.get(key) ?? null,
		setItem: (key: string, value: string) => void held.set(key, value),
	})
}

function missing(): never {
	throw new Error("SecurityError")
}

describe("sidebar collapsed flag", () => {
	it("starts expanded", () => {
		expect(readSidebarCollapsed(storage())).toBe(false)
	})

	it("reads back what was stored", () => {
		const held = storage()
		storeSidebarCollapsed(true, held)
		expect(readSidebarCollapsed(held)).toBe(true)
		storeSidebarCollapsed(false, held)
		expect(readSidebarCollapsed(held)).toBe(false)
	})

	it("stays expanded and quiet when storage is not there", () => {
		expect(() => storeSidebarCollapsed(true, missing)).not.toThrow()
		expect(readSidebarCollapsed(missing)).toBe(false)
	})
})
