# Chat

This module is the answering side of the application: a public endpoint that takes a question, retrieves the law that bears on it, and streams back an answer whose every claim carries a citation — or refuses a question the corpus does not cover.

```bash
curl -N localhost:8000/chat -H 'content-type: application/json' \
  -d '{"question": "how is energy at berth reported"}'
```

## The graph

```
START ─┬→ rewrite ─┬→ decompose ──┐                      a follow-up; DECOMPOSE_ENABLED
       │           └──────────────┤
       ├→ decompose ──────────────┤                       DECOMPOSE_ENABLED
       │                          ↓
       └──────────────────────→ retrieve ─┬→ refuse ──────────────→ END   nothing opened the gate, or the loop found nothing or refused
                                          │      ↑
                                          ├→ assess ⇄ assess_tools       while assess asks and the budget remains
                                          │      │
                                          └──────┴→ synthesize ────→ END   the context is settled
```

`rewrite` runs only on a follow-up — a question sent with a `thread_id` whose thread has answered turns. It makes one blocking model call restating the question to stand on its own, so "what penalties does it impose?" says what "it" is. Retrieve and decompose work from the restated question, while the answer is written to the question as asked, with the earlier turns in front of the model as question and answer pairs, markers stripped. The call is best-effort: one that fails or answers off its shape searches the question as asked.

`decompose` makes one blocking model call splitting the question into one search per thing it asks, capped at `DECOMPOSE_MAX_PARTS`. A single-part question is searched exactly as asked. The node is off by default: `DECOMPOSE_ENABLED=false` takes the edge straight to `retrieve` and records no step. The call is best-effort like rewrite's.

`retrieve` searches the corpus for each query at once and checks each query's hits against the refusal gate on their own ([`../retrieval/README.md`](../retrieval/README.md)), so an out-of-corpus part cannot bring sub-bar hits into the context. The survivors are interleaved by rank, each query's first hit before any query's second. If no query clears the gate, a dataset tool can still open it: a question that names something in the tool's data, uses its card terms, or sits close to its card (`MIN_CARD_SIMILARITY`) goes to assess with an empty context. Otherwise the edge takes us to `refuse`, which returns fixed wording and calls no model.

Past the gate, the assess loop runs. `assess` makes one blocking model call and answers with the tool calls that would fill what the context is missing: a fresh `search`, a `follow_reference` fetching a division the context cites, or an `mrv_query` reading THETIS-MRV emission figures. `assess_tools` runs them at once and appends what they find after the earlier blocks. The loop ends when assess asks for nothing or `ASSESS_MAX_ROUNDS` is spent, and `ASSESS_ENABLED=false` skips it. Either way, `synthesize` makes one streamed call answering from the numbered blocks.

The gate only asks whether the hits are junk, so a question about another regime, or a fact no law states, clears it on real text about something adjacent. For that, assess has a `refuse` tool, called alone to say why nothing in the context bears on the question. It routes the round to the same `refuse` node, recording reason `insufficient_context` against the gate's `nothing_retrieved`. Called beside a search or fetch it is dropped and the fetch runs, so the bias stays toward answering. `ASSESS_MAY_REFUSE=false` takes the tool away, so such a question reaches synthesize and is declined in the model's own words.

Two bounds keep the loop honest. A search's hits face the same score bar `retrieve` holds its own to, and the merge stops once the loop has added `ASSESS_EXTRA_CHUNKS` on top of what retrieval left.

The loop is best-effort: a failed assess call or a failed tool call costs the answer that round's context, never the request. The diagram is hand-drawn from `graph/service.py`.

### Following references

Some questions are only answerable a step or two away from where search lands. Ask what a *voyage* is under FuelEU and search finds FuelEU Article 3 — which does not say. It says the answer is in Article 3 of another act.

The loop handles that because every block assess reads is printed with the addresses it cites:

```
[2] (32023R1805, Article 3)
    'voyage' means voyage as defined in Article 3, point (c), of Regulation (EU) 2015/757 ...
    cites: 32015R0757 Article 3, point (c)
```

So assess never has to fetch a block to discover where it points. It asks for `32015R0757 Article 3, point (c)` directly, and the follow lands on the part of the definitions article that lists `(c)`.

That is why the loop is bounded by **how many things it can fetch, not how far away they are**. `ASSESS_MAX_CALLS` sets the width, four addresses in one round. A second round only helps when a fetched block shows an address nothing had shown before, so `ASSESS_MAX_ROUNDS` defaults to 1: on the golden dataset's multi-hop cases a second round changed no score.

A call that would only re-fetch a paragraph the context already shows in full is dropped before the four are counted, so the width goes to what is missing.

## The stream

`POST /chat` responds with SSE. Five frame types, in this order:

| Event | When | Data |
| ----- | ---- | ---- |
| `step` | twice per node or tool call: as it starts, and again once it finishes | what the step was and whether it has finished, then how long it took, the tokens it spent and the model, and for a tool call what it was for |
| `sources` | once, as soon as the context settles — after retrieval, or after the loop's last round | the context blocks, each bound to the `[n]` marker the answer will cite it by |
| `text` | repeatedly as the model writes, or once for a refusal | a fragment of the answer |
| `done` | last, on a completed stream, once the turn is recorded | the thread id, which a follow-up sends back as `thread_id`, and the request id, which `PUT /chat/{request_id}/vote` names (null when the write failed) |
| `error` | last, in place of everything after it | the app's one error shape, with the request id |

Markers run `1..n` in context order and match the numbering the prompt gave the model, so a client can resolve `[2]` to an act and article on its own.

A thread holds at most `CHAT_THREAD_TURNS` answered turns. The next question on a full one ends in an `error` frame naming `ThreadFullError`, and the client starts a new thread by sending no `thread_id`.

## The answer cache

`cache_stream` decorates `run_graph`. A first question, one sent without a `thread_id`, is looked up in Redis, and a hit sends `sources`, the whole answer as one `text` frame, and `done`, with no `step` frames and no spend-cap check. Only an answered first question is kept.

## The ledger

Every request is recorded however it ended — answered, served from the cache, refused, errored, or abandoned by the client — as a `chat_requests` row with a `chat_request_steps` row per step, holding the question, the outcome, the reader's vote, and the time, tokens and cost each step spent. A step is a graph node, or one tool call an assess round ran, prefixed `tool_` so one column holds both. The spend cap sums its cost, and a slow path is diagnosed from it.

It is the tracing, in place of a tracing library: a flat span list ordered by `position`, where a tool step's parent is the assess step before it.

The row also holds the thread and the answer, so a thread's answered rows, cached ones included, oldest first, are a follow-up's history and the ledger is the conversation store.
