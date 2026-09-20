import * as Sentry from "@sentry/react"

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
const READY_CALLBACK = "onRegRagTurnstileReady"

/** What the widget stamps on every token, and what the backend requires a token to carry. */
const ACTION = "chat"

/** How long a question waits for a token before going without one. Cloudflare's own
 * challenge can take a few seconds when it decides the visitor needs one. */
const MINT_TIMEOUT_MS = 15_000

/** Where the widget shows itself on the rare question Cloudflare wants the visitor to click
 * something for. An interaction-only widget takes no space until that happens, so this sits
 * over the page invisibly until it is needed, and centred rather than hidden, since a
 * challenge the visitor cannot see is one they can never pass. */
const CONTAINER_CLASS =
	"fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2"

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
type DeliverToken = (token: string | null) => void

/** Renders the page's one widget, reporting every token it mints to `deliver`. Replaced in
 * tests, which have no document to render into. */
export type OpenWidget = (
	sitekey: string,
	deliver: DeliverToken,
) => Promise<Widget>

let reportedMissingSitekey = false

/** Say once that this build carries no sitekey. Nothing server-side can see a build
 * variable, so a deploy that turned the backend check on would otherwise refuse every
 * question with no sign of why. */
function reportMissingSitekey(): void {
	if (reportedMissingSitekey) return
	reportedMissingSitekey = true
	Sentry.captureMessage("Turnstile sitekey missing from the build", "warning")
}

/** The mint in flight, which whatever the widget reports back belongs to. */
let pending: DeliverToken | null = null

let widget: Promise<Widget> | null = null
let script: Promise<TurnstileApi> | null = null

function deliverToken(token: string | null): void {
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
		// A question asked once the network is back refetches rather than inheriting this.
		script = null
		throw failure
	})
	return script
}

const openTurnstile: OpenWidget = async (sitekey, deliver) => {
	const turnstile = await loadScript()
	const container = document.createElement("div")
	container.className = CONTAINER_CLASS
	document.body.append(container)
	const id = turnstile.render(container, {
		sitekey,
		action: ACTION,
		execution: "execute",
		appearance: "interaction-only",
		callback: deliver,
		"error-callback": () => deliver(null),
		"expired-callback": () => deliver(null),
		"timeout-callback": () => deliver(null),
	})
	return {
		execute: () => turnstile.execute(id),
		reset: () => turnstile.reset(id),
	}
}

/** One token from the widget: the last one is thrown away first, since Cloudflare redeems
 * each token once and a thread's second question needs its own. A mint still waiting when
 * the next one starts gives up there and then, rather than taking the new one's token. */
function awaitToken(rendered: Widget): Promise<string | null> {
	return new Promise((resolve) => {
		pending?.(null)
		const finish = (token: string | null) => {
			if (pending !== finish) return
			clearTimeout(timer)
			pending = null
			resolve(token)
		}
		pending = finish
		const timer = setTimeout(() => finish(null), MINT_TIMEOUT_MS)
		rendered.reset()
		rendered.execute()
	})
}

/** A fresh token for one question, or null when there is no sitekey to mint against, the
 * widget could not be rendered, or it produced nothing in time. The question then goes
 * without the header, and the backend refuses it if its own check is on. */
export async function mintToken(
	openWidget: OpenWidget = openTurnstile,
): Promise<string | null> {
	const sitekey = import.meta.env.VITE_TURNSTILE_SITE_KEY
	if (!sitekey) {
		reportMissingSitekey()
		return null
	}
	try {
		widget ??= openWidget(sitekey, deliverToken)
		return await awaitToken(await widget)
	} catch {
		widget = null
		return null
	}
}
