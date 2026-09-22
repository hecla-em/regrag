import { createParser, type EventSourceMessage } from "eventsource-parser"
import { readClientId } from "@/lib/client-id"
import { mintToken } from "@/lib/turnstile"
import type {
	ChatQuery,
	ChatStreamEvent,
	ErrorBody,
	ErrorResponse,
	Vote,
} from "./types"

export const API_URL = import.meta.env.VITE_API_URL

export class ApiError extends Error {
	readonly status: number
	readonly body: ErrorBody

	constructor(status: number, body: ErrorBody) {
		super(body.message)
		this.name = "ApiError"
		this.status = status
		this.body = body
	}
}

async function readErrorBody(response: Response): Promise<ApiError> {
	const fallback = `Request failed: ${response.status}`
	try {
		const body: Partial<ErrorResponse> = await response.json()
		return new ApiError(response.status, {
			error: body.error || "ApiError",
			message: body.message || fallback,
		})
	} catch {
		return new ApiError(response.status, {
			error: "ApiError",
			message: fallback,
		})
	}
}

/** Any thrown value as an error body: an ApiError carries the backend's, anything else names itself. */
export function describeError(error: unknown): ErrorBody {
	if (error instanceof ApiError) return error.body
	if (error instanceof Error)
		return { error: error.name, message: error.message }
	return { error: "Error", message: "Request failed" }
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
	const token = await mintToken()
	const response = await apiFetch("/chat", {
		method: "POST",
		headers: {
			"content-type": "application/json",
			"X-Client-ID": readClientId(),
			...(token === null ? {} : { "CF-Turnstile-Response": token }),
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

/** Records the reader's vote on the answer a request gave; null takes it back. */
export async function sendVote(
	requestId: string,
	vote: Vote | null,
): Promise<void> {
	await apiFetch(`/chat/${requestId}/vote`, {
		method: "PUT",
		headers: {
			"content-type": "application/json",
			"X-Client-ID": readClientId(),
		},
		body: JSON.stringify({ vote }),
	})
}
