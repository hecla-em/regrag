const CLIENT_ID_KEY = "regrag:client-id"

/** crypto.randomUUID needs a secure context, which a plain-HTTP host is not; random bytes
 * do not. */
function mintId(): string {
	if (crypto.randomUUID) return crypto.randomUUID()
	const bytes = crypto.getRandomValues(new Uint8Array(16))
	return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
		"",
	)
}

/** The id this browser sends on every question, minted once and kept in storage;
 * without storage (private mode, blocked site data) each call mints its own. */
export function readClientId(storage: Storage | null): string {
	try {
		const held = storage?.getItem(CLIENT_ID_KEY)
		if (held) return held
		const minted = mintId()
		storage?.setItem(CLIENT_ID_KEY, minted)
		return minted
	} catch {
		return mintId()
	}
}

function browserStorage(): Storage | null {
	try {
		return globalThis.localStorage ?? null
	} catch {
		return null
	}
}

export const clientId: string = readClientId(browserStorage())
