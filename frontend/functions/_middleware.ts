export const onRequest: PagesFunction = async (context) => {
	const url = new URL(context.request.url)

	if (url.hostname.endsWith(".pages.dev")) {
		url.hostname = "ask.hecla-em.com"
		return Response.redirect(url.toString(), 301)
	}

	return context.next()
}
