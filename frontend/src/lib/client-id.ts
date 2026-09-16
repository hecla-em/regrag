import { randomId } from "@/lib/ids"

const CLIENT_ID_KEY = "regrag:client-id"

type ClientIdStore = Pick<Storage, "getItem" | "setItem">

/** The id this browser sends on every question, minted once and kept in storage. When
 * storage is not there (private mode, blocked site data) each call mints its own. */
export function readClientId(
	storage: () => ClientIdStore = () => localStorage,
): string {
	try {
		const held = storage().getItem(CLIENT_ID_KEY)
		if (held) return held
		const minted = randomId()
		storage().setItem(CLIENT_ID_KEY, minted)
		return minted
	} catch {
		return randomId()
	}
}
