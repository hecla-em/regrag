import { createParser, type EventSourceMessage } from "eventsource-parser"
import { readClientId } from "@/lib/client-id"
import type { ChatQuery, ChatStreamEvent, ErrorResponse } from "./types"

export const API_URL: string =
	import.meta.env.VITE_API_URL ?? "http://localhost:8000"

export class ApiError extends Error {
	readonly status: number
	/** The backend's name for the error, e.g. RateLimitedError. */
	readonly code: string

	constructor(status: number, code: string, message: string) {
		super(message)
		this.name = "ApiError"
		this.status = status
		this.code = code
	}
}

async function readErrorBody(response: Response): Promise<ApiError> {
	const fallback = `Request failed: ${response.status}`
	try {
		const body: Partial<ErrorResponse> = await response.json()
		return new ApiError(
			response.status,
			body.error || "ApiError",
			body.message || fallback,
		)
	} catch {
		return new ApiError(response.status, "ApiError", fallback)
	}
}

async function apiFetch(path: string, init: RequestInit): Promise<Response> {
	const response = await fetch(`${API_URL}${path}`, init)
	if (!response.ok) throw await readErrorBody(response)
	return response
}

function toStreamEvent(message: EventSourceMessage): ChatStreamEvent | null {
	switch (message.event) {
		case "sources":
		case "step":
		case "text":
		case "done":
		case "error":
			return { event: message.event, data: JSON.parse(message.data) }
		default:
			return null
	}
}

/** Yields the backend's typed SSE events as they arrive; throws ApiError on a non-2xx response. */
export async function* streamChat(
	body: ChatQuery,
	signal: AbortSignal,
): AsyncGenerator<ChatStreamEvent> {
	const response = await apiFetch("/chat", {
		method: "POST",
		headers: {
			"content-type": "application/json",
			"X-Client-ID": readClientId(),
		},
		body: JSON.stringify(body),
		signal,
	})
	if (response.body === null) {
		throw new Error("Chat response had no body to stream")
	}

	const events: ChatStreamEvent[] = []
	const parser = createParser({
		onEvent(message) {
			const event = toStreamEvent(message)
			if (event !== null) events.push(event)
		},
	})
	const decoder = new TextDecoder()
	const reader = response.body.getReader()
	try {
		while (true) {
			const { done, value } = await reader.read()
			if (done) break
			parser.feed(decoder.decode(value, { stream: true }))
			while (events.length > 0) yield events.shift() as ChatStreamEvent
		}
	} catch (error) {
		reader.cancel().catch(() => undefined)
		throw error
	} finally {
		reader.releaseLock()
	}
}
