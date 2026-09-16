import { describe, expect, it } from "vitest"
import { readClientId } from "./client-id"

function storage() {
	const held = new Map<string, string>()
	return () => ({
		getItem: (key: string) => held.get(key) ?? null,
		setItem: (key: string, value: string) => void held.set(key, value),
	})
}

describe("readClientId", () => {
	it("mints an id once and hands the same one back after", () => {
		const held = storage()
		const first = readClientId(held)
		expect(first).toMatch(/^[0-9a-f]{32}$/)
		expect(readClientId(held)).toBe(first)
	})

	it("mints a fresh id per storage", () => {
		expect(readClientId(storage())).not.toBe(readClientId(storage()))
	})

	it("stays usable when storage is not there", () => {
		const missing = () => {
			throw new Error("SecurityError")
		}
		expect(readClientId(missing)).toMatch(/^[0-9a-f]{32}$/)
	})
})
