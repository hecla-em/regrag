# Frontend

React interface for RegRag: one chat page that streams a cited answer and lets
each citation be opened against the article it came from.

## Stack

| Component        | Technology                                                        |
| ---------------- | ----------------------------------------------------------------- |
| Framework        | [React 19](https://github.com/facebook/react)                     |
| Language         | [TypeScript](https://github.com/microsoft/TypeScript)             |
| Build Tool       | [Vite](https://github.com/vitejs/vite)                            |
| Routing          | [TanStack Router](https://github.com/TanStack/router)             |
| Data Fetching    | [TanStack Query](https://github.com/TanStack/query)               |
| Styling          | [Tailwind CSS](https://github.com/tailwindlabs/tailwindcss)       |
| UI Components    | [shadcn/ui](https://github.com/shadcn-ui/ui) on [Base UI](https://base-ui.com/) |
| Markdown         | [react-markdown](https://github.com/remarkjs/react-markdown)      |
| SSE Parsing      | [eventsource-parser](https://github.com/rexxars/eventsource-parser) |
| API Types        | [openapi-typescript](https://github.com/openapi-ts/openapi-typescript) |
| Linter/Formatter | [Biome](https://github.com/biomejs/biome)                         |
| Tests            | [Vitest](https://github.com/vitest-dev/vitest)                    |
| E2E Tests        | [Playwright](https://github.com/microsoft/playwright)             |
| Package Manager  | [pnpm](https://github.com/pnpm/pnpm)                              |

## Development

Prerequisites: [pnpm](https://pnpm.io/installation), and the backend running on
`http://localhost:8000` (see [`../backend/README.md`](../backend/README.md)).

```bash
pnpm install
cp .env.example .env    # dev and build fail without VITE_API_URL and VITE_SITE_URL
pnpm dev
```

The app is then on `http://localhost:5173`.

## Scripts

| Command             | Description                                        |
| ------------------- | -------------------------------------------------- |
| `pnpm dev`          | Start the dev server                               |
| `pnpm build`        | Type-check and build for production                |
| `pnpm lint`         | Check formatting and lint with Biome               |
| `pnpm check`        | Check and auto-fix with Biome                      |
| `pnpm test`         | Run the unit tests with Vitest                     |
| `pnpm e2e`          | Run the end-to-end tests with Playwright           |
| `pnpm knip`         | Report unused files, exports and dependencies      |
| `pnpm generate-api` | Regenerate `src/api/schema.ts` from `openapi.json` |

`pnpm generate-api` expects an `openapi.json` already exported from the backend;
[`../scripts/generate-client.sh`](../scripts/generate-client.sh) does both steps,
dumping the FastAPI schema and then regenerating the types.

## End-to-end tests

`e2e/` drives the built site in Chromium against the real backend, with only the
model and embeddings faked. Playwright starts both: the backend launcher
(`backend/tests/e2e/server.py`) on `:8000`, seeding its own `regrag_e2e` database
and Redis index 2, and `vite preview` on `:5173`. Both ports must be free.

```bash
docker compose -f ../backend/compose.yaml up -d db redis
pnpm exec playwright install chromium    # once
pnpm e2e
```

## Layout

```
src/
├── api/                 # Fetch client, SSE decoding, generated schema types
├── components/
│   ├── pages/chat/      # The chat page: prompt, answer, citations, sources
│   ├── shared/errors/   # Error and not-found boundaries
│   └── ui/              # Base UI primitives
├── hooks/               # use-chat-stream: turn state as frames arrive
├── lib/                 # Citation parsing and helpers
└── routes/              # File-based routing (TanStack Router)
```

## Streaming

`POST /chat` answers over SSE. `api/client.ts` decodes the frames and
`use-chat-stream` folds them into one turn: a `sources` frame naming the context
blocks the answer may cite, `text` frames appended as the model writes, then
`done` — or a single `error` frame, which marks the turn failed. Citation
markers in the streamed markdown are rewritten and split in `lib/citations.ts`,
then rendered as chips that open the cited article in the source panel.
