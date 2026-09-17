const SIDEBAR_COLLAPSED_KEY = "regrag:sidebar-collapsed"

type FlagStore = Pick<Storage, "getItem" | "setItem">

/** Whether this browser last left the sidebar collapsed. Expanded when storage is not there. */
export function readSidebarCollapsed(
	storage: () => FlagStore = () => localStorage,
): boolean {
	try {
		return storage().getItem(SIDEBAR_COLLAPSED_KEY) === "true"
	} catch {
		return false
	}
}

/** Keeps the choice for the next visit, and forgets it silently where storage is blocked. */
export function storeSidebarCollapsed(
	collapsed: boolean,
	storage: () => FlagStore = () => localStorage,
): void {
	try {
		storage().setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed))
	} catch {
		return
	}
}
