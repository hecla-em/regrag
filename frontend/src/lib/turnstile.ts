const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
const READY_CALLBACK = "onRegRagTurnstileReady"

/** What the widget stamps on every token, and what the backend requires a token to carry. */
const ACTION = "chat"

/** How long a question waits for a token before going without one. Cloudflare's own
 * challenge can take a few seconds when it decides the visitor needs one. */
const MINT_TIMEOUT_MS = 15_000

type TurnstileOptions = {
	sitekey: string
	action: string
	execution: "execute"
	appearance: "interaction-only"
	callback: (token: string) => void
	"error-callback": () => void
	"expired-callback": () => void
	"timeout-callback": () => void
}

type TurnstileApi = {
	render: (container: HTMLElement, options: TurnstileOptions) => string
	execute: (widgetId: string) => void
	reset: (widgetId: string) => void
}

declare global {
	interface Window {
		turnstile?: TurnstileApi
	}
}

/** The rendered widget, as minting uses it: ask for a token, throw the last one away. */
export type Widget = {
	execute: () => void
	reset: () => void
}

/** What a widget reports a mint with: the token, or null when it could not produce one. */
type Deliver = (token: string | null) => void

/** Renders the page's one widget, reporting every token it mints to `deliver`. Replaced in
 * tests, which have no document to render into. */
export type OpenWidget = (sitekey: string, deliver: Deliver) => Promise<Widget>

/** The mint in flight, which whatever the widget reports back belongs to. */
let pending: Deliver | null = null

let widget: Promise<Widget> | null = null
let script: Promise<TurnstileApi> | null = null

function deliver(token: string | null): void {
	pending?.(token)
}

function loadScript(): Promise<TurnstileApi> {
	script ??= new Promise<TurnstileApi>((resolve, reject) => {
		Reflect.set(window, READY_CALLBACK, () => {
			const api = window.turnstile
			if (api === undefined)
				reject(new Error("Turnstile loaded without its API"))
			else resolve(api)
		})
		const tag = document.createElement("script")
		tag.src = `${SCRIPT_URL}?render=explicit&onload=${READY_CALLBACK}`
		tag.async = true
		tag.defer = true
		tag.onerror = () => reject(new Error("Turnstile script did not load"))
		document.head.append(tag)
	}).catch((failure: unknown) => {
		// Not held as a failed load, so a question asked after the network comes back
		// fetches the script again rather than inheriting the first attempt forever.
		script = null
		throw failure
	})
	return script
}

const openTurnstile: OpenWidget = async (sitekey, report) => {
	const turnstile = await loadScript()
	const container = document.createElement("div")
	container.style.display = "none"
	document.body.append(container)
	const id = turnstile.render(container, {
		sitekey,
		action: ACTION,
		execution: "execute",
		appearance: "interaction-only",
		callback: report,
		"error-callback": () => report(null),
		"expired-callback": () => report(null),
		"timeout-callback": () => report(null),
	})
	return {
		execute: () => turnstile.execute(id),
		reset: () => turnstile.reset(id),
	}
}

/** One token from the widget: the last one is thrown away first, since Cloudflare redeems
 * each token once and a thread's second question needs its own. */
function awaitToken(open: Widget): Promise<string | null> {
	return new Promise((resolve) => {
		let timer: ReturnType<typeof setTimeout> | undefined
		const finish = (token: string | null) => {
			clearTimeout(timer)
			pending = null
			resolve(token)
		}
		pending = finish
		timer = setTimeout(() => finish(null), MINT_TIMEOUT_MS)
		open.reset()
		open.execute()
	})
}

/** A fresh token for one question, or null when there is no sitekey to mint against, the
 * widget could not be rendered, or it produced nothing in time. The question then goes
 * without the header, and the backend refuses it if its own check is on. */
export async function mintToken(
	open: OpenWidget = openTurnstile,
): Promise<string | null> {
	const sitekey = import.meta.env.VITE_TURNSTILE_SITE_KEY
	if (!sitekey) return null
	try {
		widget ??= open(sitekey, deliver)
		return await awaitToken(await widget)
	} catch {
		widget = null
		return null
	}
}
