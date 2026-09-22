import * as Sentry from "@sentry/react"

const SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
const READY_CALLBACK = "onRegRagTurnstileReady"
const ACTION = "chat"
const MINT_TIMEOUT_MS = 15_000

/** Centred, and shown only while a challenge waits on a click: Turnstile leaves a passed one on screen. */
const CONTAINER_CLASS =
	"fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2"
const HIDDEN_CLASS = "invisible"

type TurnstileOptions = {
	sitekey: string
	action: string
	execution: "execute"
	appearance: "interaction-only"
	callback: (token: string) => void
	"error-callback": () => void
	"expired-callback": () => void
	"timeout-callback": () => void
	"before-interactive-callback": () => void
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

type Widget = {
	execute: () => void
	reset: () => void
	hide: () => void
}

type DeliverToken = (token: string | null) => void

let reportedMissingSitekey = false
let pending: DeliverToken | null = null
let mintTimer: ReturnType<typeof setTimeout> | undefined
let widget: Promise<Widget> | null = null
let script: Promise<TurnstileApi> | null = null

function reportMissingSitekey(): void {
	if (reportedMissingSitekey) return
	reportedMissingSitekey = true
	Sentry.captureMessage("Turnstile sitekey missing from the build", "warning")
}

function deliverToken(token: string | null): void {
	pending?.(token)
}

/** A challenge the reader must click runs to Cloudflare's own timeout, not the mint's. */
function showChallenge(container: HTMLElement): void {
	clearTimeout(mintTimer)
	container.classList.remove(HIDDEN_CLASS)
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
		script = null
		throw failure
	})
	return script
}

async function openWidget(sitekey: string): Promise<Widget> {
	const turnstile = await loadScript()
	const container = document.createElement("div")
	container.className = `${CONTAINER_CLASS} ${HIDDEN_CLASS}`
	document.body.append(container)
	const id = turnstile.render(container, {
		sitekey,
		action: ACTION,
		execution: "execute",
		appearance: "interaction-only",
		callback: deliverToken,
		"error-callback": () => deliverToken(null),
		"expired-callback": () => deliverToken(null),
		"timeout-callback": () => deliverToken(null),
		"before-interactive-callback": () => showChallenge(container),
	})
	return {
		execute: () => turnstile.execute(id),
		reset: () => turnstile.reset(id),
		hide: () => container.classList.add(HIDDEN_CLASS),
	}
}

/** One fresh token, since Cloudflare redeems each once. A superseded mint gives up. */
function awaitToken(rendered: Widget): Promise<string | null> {
	return new Promise((resolve) => {
		pending?.(null)
		const finish = (token: string | null) => {
			if (pending !== finish) return
			clearTimeout(mintTimer)
			pending = null
			rendered.hide()
			resolve(token)
		}
		pending = finish
		mintTimer = setTimeout(() => finish(null), MINT_TIMEOUT_MS)
		rendered.reset()
		rendered.execute()
	})
}

/** A token for one question, or null when none could be minted. */
export async function mintToken(): Promise<string | null> {
	const sitekey = import.meta.env.VITE_TURNSTILE_SITE_KEY
	if (!sitekey) {
		reportMissingSitekey()
		return null
	}
	try {
		widget ??= openWidget(sitekey)
		return await awaitToken(await widget)
	} catch {
		widget = null
		return null
	}
}
