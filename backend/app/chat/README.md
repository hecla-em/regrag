# Chat

This module is the answering side of the application: one public endpoint that takes a question, retrieves the law that bears on it, and streams back an answer whose every claim carries a citation — or refuses a question the corpus does not cover.

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
       └──────────────────────→ retrieve ─┬→ refuse ──────────────→ END   nothing cleared the gate, or assess refused
                                          │      ↑
                                          ├→ assess ⇄ assess_tools       while assess asks and the budget remains
                                          │      │
                                          └──────┴→ synthesize ────→ END   the context is settled
```

`rewrite` runs only on a follow-up — a question sent with a `thread_id` whose thread has answered turns. It makes one blocking model call, answering in a fixed shape with the question restated to stand on its own: "what penalties does it impose?" searched as typed clears no gate, so the thread's earlier turns are read to say what "it" is. Retrieve and decompose then work from the restated question, while the answer is written to the question as asked, with the earlier turns in front of the model as message pairs — questions and answers only, markers stripped, never their context blocks. A first question takes the edge below and records no step. The call is best-effort like decompose's: one that fails or answers off its shape searches the question as asked.

`decompose` makes one blocking model call, answering in a fixed shape with the searches the question needs, one per thing it asks, capped at `DECOMPOSE_MAX_PARTS`. A question asking one thing comes back as one query and is searched exactly as asked, so switching the node off and asking a single-part question run the same retrieval; the only trace is the recorded step. `DECOMPOSE_ENABLED=false` takes the edge straight to `retrieve` and records no step. The call is best-effort: one that fails or answers off its shape logs and searches the question as asked.

`retrieve` searches the corpus for each query — the parts decompose split off, or the question as asked — each on its own session and at once, and checks each query's hits against the refusal gate on their own ([`../retrieval/README.md`](../retrieval/README.md)), so an out-of-corpus part cannot bring sub-bar hits into the context. The survivors are interleaved by rank, each query's first hit before any query's second, and every query's hits, gated or not, stay on the state as `hits`. If no query clears the gate the context is empty, and the edge takes us to `refuse`, which returns fixed wording and calls no model.

Otherwise the assess loop runs. `assess` makes one blocking model call and answers with the tool calls that would fill what the context is missing — a fresh `search`, or a `follow_reference` fetching a division the context cites. `assess_tools` runs them and merges what they find in, keeping the earlier blocks in place so the `[n]` markers a client already holds keep meaning what they meant. It ends when assess asks for nothing or `ASSESS_MAX_ROUNDS` is spent; `ASSESS_ENABLED=false` skips it entirely, leaving the two-node graph this started as. Either way, `synthesize` makes one streamed call answering from the numbered blocks.

The gate only asks whether the hits are junk, so a question about another regime, or a fact no law states, clears it on real text about something adjacent. Assess has a third tool for that: `refuse`, explaining why nothing in the context bears on the question and no search or fetch would change that. It fetches nothing, its step carrying the explanation, and leaves a `Refusal` on the state — reason `insufficient_context`, against the `nothing_retrieved` a gate refusal records — which routes the round to the same `refuse` node: the fixed wording, no answer written, and `refused` in the ledger either way. Called beside a search or fetch it is dropped and the fetch runs, so the bias stays toward answering. `ASSESS_MAY_REFUSE=false` takes the tool off the surface and its sentence out of the prompt, so such a question reaches synthesize and is declined in the model's own words.

Three bounds keep the loop honest. A search's hits face the same score bar `retrieve` holds its own to, so what the gate would refuse to answer from cannot arrive by the back door. The merge stops once the loop has added `ASSESS_EXTRA_CHUNKS` on top of what retrieval left. And each call runs on its own session, so one that fails on the database costs its own result and no other's.

Every model call runs at `CHAT_TEMPERATURE`, which is 0 — an answer quoting law back gains nothing from sampling variety, and assess sampling differently changes the context the answer is built from. Decompose sampling differently changes which searches run.

The loop is best-effort: a failed assess call or a failed tool call costs the answer that round's context, never the request. The diagram is hand-drawn, and a test holds the compiled graph to the edge list it was drawn from.

### Following references

Some questions are only answerable a step or two away from where search lands. Ask what a *voyage* is under FuelEU and search finds FuelEU Article 3 — which does not say. It says the answer is in Article 3 of another act. The text that answers the question is never in the article the question is about.

The loop handles that because of how the context is written for it. Every block assess reads is printed with the addresses it cites, like a footnote list under the paragraph:

```
[2] (32023R1805, Article 3)
    'voyage' means voyage as defined in Article 3, point (c), of Regulation (EU) 2015/757 ...
    cites: 32015R0757 Article 3, point (c)
```

So assess never has to fetch a block in order to discover where it points — the destination is already on the page. It asks for `32015R0757 Article 3, point (c)` directly, in one go, and the follow lands on the part of the definitions article that lists `(c)`, since each chunk records the points its text opens lines with.

That is why the loop is bounded by **how many things it can fetch, not how far away they are**. `ASSESS_MAX_CALLS` sets the width — four addresses in one round — and a chain three acts long costs the same single round as a chain one act long, as long as each address is visible before it is needed. A second round would only earn its cost if reading a fetched block revealed an address that nothing had shown before. `ASSESS_MAX_ROUNDS` therefore defaults to 1: measured against the multi-hop cases in the golden dataset, a second round changed no score and cost roughly a third of the tokens and two seconds a question.

A call that would only re-fetch a paragraph the context already shows in full is dropped before the four are counted, so the width goes to what is missing.

The reach has a real edge, though. A question needing more than `ASSESS_MAX_CALLS` separate fetches cannot be answered in full however good assess is, and neither can one whose next address only appears in text nobody has fetched yet.

## The stream

`POST /chat` responds with SSE. Five frame types, in this order:

| Event | When | Data |
| ----- | ---- | ---- |
| `step` | twice per node or tool call: as it starts, and again once it finishes | what the step was and whether it has finished; once it has, how long it took and the tokens it spent; for a tool call, what it was for |
| `sources` | once, as soon as the context settles — after retrieval, or after the loop's last round | the context blocks, each bound to the `[n]` marker the answer will cite it by |
| `text` | repeatedly as the model writes, or once for a refusal | a fragment of the answer |
| `done` | last, on a completed stream | the thread id the turn was recorded under; a follow-up sends it back as `thread_id` |
| `error` | last, in place of everything after it | the app's one error shape, with the request id |

Markers run `1..n` in context order and match the numbering the prompt gave the model, so a client can resolve `[2]` to an act and article on its own.

A thread holds at most `CHAT_THREAD_TURNS` answered turns; the next question on a full one ends in an `error` frame naming `ThreadFullError`, and the client starts a new thread by sending no `thread_id`.

## The ledger

Every request is recorded however it ended — answered, refused, errored, or abandoned by the client — as a `chat_requests` row with a `chat_request_steps` row per step it ran through, holding the question, the outcome, and the timings and tokens each step spent. A step is a graph node, or one tool call an assess round ran, named `tool_search` / `tool_follow_reference` so one column holds both. It is what a spend cap sums over and what a slow path is diagnosed from.

This is deliberately the tracing, in place of a tracing library: the request row has to exist for the spend cap anyway, and the per-step timings come with it. It is a flat span list ordered by `position`, not a tree — a tool step's parent is the assess step before it — which is enough while the graph nests only one level deep.

The row also holds the thread the request belongs to and the answer it gave. That is what a follow-up reads back: the thread's answered rows, oldest first, are its history, so the ledger is the conversation store and nothing else needs to be.
