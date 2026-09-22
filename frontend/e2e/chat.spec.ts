import { expect, type Page, test } from "@playwright/test"

const ON_TOPIC =
	"What is the greenhouse gas intensity limit for energy used on board a ship?"
const LONG_ANSWER_QUESTION = `${ON_TOPIC} Explain at length.`
const OFF_TOPIC = "How do I bake sourdough bread at home?"
const ANSWER = "The limit falls over time"
const REFUSAL = "The corpus doesn't cover this."

async function ask(page: Page, question: string) {
	await page.getByRole("textbox", { name: "Ask a question" }).fill(question)
	await page.getByRole("button", { name: "Send" }).click()
}

/** The chip a finished run leaves above its answer, by how many steps it took. */
function settledSteps(page: Page, label: string) {
	return page.getByRole("status").filter({ hasText: new RegExp(`^${label} ·`) })
}

function isChatPost(url: string, method: string): boolean {
	return url.endsWith("/chat") && method === "POST"
}

function doneThreadId(body: string): string {
	const done = body.match(/event: done\r?\ndata: (.*)/)
	if (done === null) throw new Error("the stream sent no done frame")
	return JSON.parse(done[1]).thread_id
}

test.beforeEach(async ({ page }) => {
	await page.goto("/")
})

test("a question streams its steps, its answer and the sources it cites", async ({
	page,
}) => {
	await ask(page, ON_TOPIC)

	await expect(page.getByText(ANSWER)).toBeVisible()
	await expect(
		page.getByRole("button", { name: "Open source 1" }),
	).toBeVisible()

	await settledSteps(page, "2 steps").click()
	await expect(page.getByText("Searched the corpus")).toBeVisible()
	await expect(page.getByText("Wrote the answer")).toBeVisible()
	await page.keyboard.press("Escape")

	await page.getByRole("button", { name: /1 source/ }).click()
	await expect(page.getByText("Regulation (EU) 2023/1805")).toBeVisible()
})

test("a follow-up is sent on the thread the first answer opened", async ({
	page,
}) => {
	const first = page.waitForResponse((response) =>
		isChatPost(response.url(), response.request().method()),
	)
	await ask(page, ON_TOPIC)
	const threadId = doneThreadId(await (await first).text())

	const second = page.waitForRequest((request) =>
		isChatPost(request.url(), request.method()),
	)
	await ask(page, "And from 2030?")

	expect((await second).postDataJSON().thread_id).toBe(threadId)
	await expect(settledSteps(page, "3 steps")).toBeVisible()
})

test("stopping mid-answer settles the turn and frees the input", async ({
	page,
}) => {
	await ask(page, LONG_ANSWER_QUESTION)
	await expect(page.getByText("The limit tightens")).toBeVisible()

	await page.getByRole("button", { name: "Stop" }).click()

	await expect(settledSteps(page, "1 step")).toBeVisible()
	await page.getByRole("textbox", { name: "Ask a question" }).fill(ON_TOPIC)
	await expect(page.getByRole("button", { name: "Send" })).toBeEnabled()
})

test("a rate-limited question says so", async ({ page }) => {
	await ask(page, ON_TOPIC)
	await expect(settledSteps(page, "2 steps")).toBeVisible()
	await ask(page, "And from 2030?")
	await expect(settledSteps(page, "3 steps")).toBeVisible()

	await ask(page, "And from 2035?")

	await expect(page.getByRole("alert")).toHaveText(
		"Too many questions. Try again in a minute.",
	)
})

test("a server error shows the generic copy, and asking again replaces the failed turn", async ({
	page,
}) => {
	await page.route("**/chat", (route) =>
		route.fulfill({
			status: 500,
			headers: { "access-control-allow-origin": "http://localhost:5173" },
			json: { error: "InternalServerError", message: "Something broke" },
		}),
	)
	await ask(page, ON_TOPIC)
	await expect(page.getByRole("alert")).toContainText(
		"That answer didn't come through.",
	)

	await page.unroute("**/chat")
	await page.getByRole("button", { name: "Try again" }).click()

	await expect(page.getByText(ANSWER)).toBeVisible()
	await expect(page.getByRole("alert")).toHaveCount(0)
	await expect(settledSteps(page, "2 steps")).toHaveCount(1)
})

test("a question the corpus does not cover is refused without sources", async ({
	page,
}) => {
	await ask(page, OFF_TOPIC)

	await expect(page.getByText(REFUSAL)).toBeVisible()
	await expect(settledSteps(page, "2 steps")).toBeVisible()
	await expect(page.getByRole("button", { name: /source/ })).toHaveCount(0)
})
