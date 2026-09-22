import type { components } from "./schema"

// Chat
export type ChatQuery = components["schemas"]["ChatQuery"]
export type ChatSource = components["schemas"]["ChatSource"]
export type ChatStep = components["schemas"]["ChatStep"]
export type ChatErrorResponse = components["schemas"]["ChatErrorResponse"]
export type Vote = components["schemas"]["Vote"]
export type ChatStreamEvent =
	| components["schemas"]["SourcesEvent"]
	| components["schemas"]["StepEvent"]
	| components["schemas"]["TextEvent"]
	| components["schemas"]["DoneEvent"]
	| components["schemas"]["ErrorEvent"]

// Errors
export type ErrorResponse = components["schemas"]["ErrorResponse"]
/** The part of an error the frontend keeps: its code and what the backend said. */
export type ErrorBody = Pick<ErrorResponse, "error" | "message">
