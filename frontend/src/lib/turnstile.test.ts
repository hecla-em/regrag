import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { OpenWidget } from "./turnstile"

const SITE_KEY = "0x4AAAAAAAsitekey"

/** The module afresh, since the widget it renders is kept for the page's lifetime. */
async function loadTurnstile() {
	vi.resetModules()
	return await import("./turnstile")
}

/** A widget answering each execute with the next of these tokens, recording what it was
 * asked to do. A null is Cloudflare reporting that it minted nothing, and a missing one
 * is a widget that never answers at all. */
function fakeWidget(...tokens: (string | null | undefined)[]) {
	const calls: string[] = []
	let minted = 0
	const open: OpenWidget = async (sitekey, deliver) => {
		calls.push(`open:${sitekey}`)
		return {
			reset: () => void calls.push("reset"),
			execute: () => {
				calls.push("execute")
				const token = tokens[minted++]
				if (token !== undefined) deliver(token)
			},
		}
	}
	return { calls, open }
}

/** A widget whose script never loads, as it would behind a blocked challenges.cloudflare.com. */
const unopenable: OpenWidget = async () => {
	throw new Error("Turnstile script did not load")
}

beforeEach(() => {
	vi.stubEnv("VITE_TURNSTILE_SITE_KEY", SITE_KEY)
})

afterEach(() => {
	vi.unstubAllEnvs()
	vi.useRealTimers()
})

describe("mintToken", () => {
	it("mints nothing when no sitekey was built in", async () => {
		vi.stubEnv("VITE_TURNSTILE_SITE_KEY", "")
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget("0.token")

		expect(await mintToken(widget.open)).toBeNull()
		expect(widget.calls).toEqual([])
	})

	it("renders the widget against the sitekey and hands back its token", async () => {
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget("0.token")

		expect(await mintToken(widget.open)).toBe("0.token")
		expect(widget.calls).toEqual([`open:${SITE_KEY}`, "reset", "execute"])
	})

	it("mints a fresh token per question against the one widget", async () => {
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget("0.first", "0.second")

		expect(await mintToken(widget.open)).toBe("0.first")
		expect(await mintToken(widget.open)).toBe("0.second")
		expect(widget.calls).toEqual([
			`open:${SITE_KEY}`,
			"reset",
			"execute",
			"reset",
			"execute",
		])
	})

	it("mints nothing when the widget reports it could not", async () => {
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget(null)

		expect(await mintToken(widget.open)).toBeNull()
	})

	it("mints nothing when the widget does not answer in time", async () => {
		vi.useFakeTimers()
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget(undefined)

		const minting = mintToken(widget.open)
		await vi.advanceTimersByTimeAsync(20_000)

		expect(await minting).toBeNull()
	})

	it("stops waiting on a question the widget did answer", async () => {
		vi.useFakeTimers()
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget("0.token", undefined)

		expect(await mintToken(widget.open)).toBe("0.token")
		const minting = mintToken(widget.open)
		await vi.advanceTimersByTimeAsync(20_000)

		expect(await minting).toBeNull()
	})

	it("gives up on a mint the next question supersedes", async () => {
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget(undefined, "0.second")

		const superseded = mintToken(widget.open)
		const current = mintToken(widget.open)

		expect(await superseded).toBeNull()
		expect(await current).toBe("0.second")
	})

	it("mints nothing when the widget cannot be rendered, and tries again next question", async () => {
		const { mintToken } = await loadTurnstile()
		const widget = fakeWidget("0.token")

		expect(await mintToken(unopenable)).toBeNull()
		expect(await mintToken(widget.open)).toBe("0.token")
	})
})
