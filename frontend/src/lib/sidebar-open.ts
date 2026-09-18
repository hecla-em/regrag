import { SIDEBAR_COOKIE_NAME } from "@/components/ui/sidebar"

/** Whether this browser last left the sidebar open, from the cookie SidebarProvider writes. */
export function readSidebarOpen(cookie: string = document.cookie): boolean {
	return !cookie.split("; ").includes(`${SIDEBAR_COOKIE_NAME}=false`)
}
