import { describe, expect, it } from "vitest"
import { readClientId } from "./client-id"

function storage(): Storage {
	const held = new Map<string, string>()
	return {
		getItem: (key) => held.get(key) ?? null,
		setItem: (key, value) => void held.set(key, value),
		removeItem: (key) => void held.delete(key),
		clear: () => held.clear(),
		key: () => null,
		get length() {
			return held.size
		},
	}
}

describe("readClientId", () => {
	it("mints an id once and hands the same one back after", () => {
		const held = storage()
		const first = readClientId(held)
		expect(first).toMatch(/^[0-9a-f-]{36}$/)
		expect(readClientId(held)).toBe(first)
	})

	it("mints a fresh id per storage", () => {
		expect(readClientId(storage())).not.toBe(readClientId(storage()))
	})

	it("stays usable when storage is not there", () => {
		expect(readClientId(null)).toMatch(/^[0-9a-f-]{36}$/)
	})
})
