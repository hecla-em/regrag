# Evals

This module scores the chat graph against the authored cases in `dataset/golden.json`.

```bash
uv run evals check    # report how far the dataset has drifted from the corpus
uv run evals stamp    # record what the cited text says now
uv run evals run      # score the dataset against the current graph, and store the run
uv run evals compare 41 42  # print two stored runs side by side
uv run evals tune     # rank retrieval settings against the dataset
```

Each command self-documents: `uv run evals <command> --help` prints what it does and every flag it takes.

## Dataset

A case is a question, what a correct answer must say, and the divisions of law that answer comes from.

```json
{
  "id": "fueleu-scope-third-country-voyage",
  "kind": "in_corpus",
  "question": "If my ship sails from Rotterdam to Singapore, how much of that voyage's energy counts under FuelEU?",
  "answer": "Half of it. For a voyage arriving at or departing from an EU port ...",
  "references": [{ "celex": "32023R1805", "article": "2", "content_hashes": ["cebdcb0a2d14", "..."] }]
}
```

A case is one of two kinds. An `in_corpus` case is scored on what retrieval found and what the answer cited, so it needs an answer and, unless it holds the `dataset` trait, references. An `out_of_corpus` case asks something the corpus does not cover and is scored on refusal alone.

### Traits

A case may also hold `traits`, which say what it tests and change no scoring:

| Trait | What the question demands |
| ----- | ------------------------- |
| `multi_hop` | The answer sits a chain of citations away from where search lands |
| `multi_part` | The question asks more than one thing in one sentence, so each part needs its own retrieval |
| `dataset` | The answer needs a figure from a dataset tool, so the case may name no corpus reference |

A run, tune or stamp can select on a trait with `--trait multi_part`, on a kind with `--kind out_of_corpus`, or on an id substring with `--case fueleu`, and the three narrow together.

### Ids

An id reads like a test name: what would have to break for the case to fail. Kind and traits are fields, so neither appears in the id.

- An in-corpus id is `<area>-<what it asks>`: `fueleu-borrowing-limits`, `mrv-verification-report`.
- An out-of-corpus id is `<why the corpus cannot answer>-<what it asks>`: `unrelated-topic-airline-luggage`, `adjacent-regime-imo-cii-rating`, `fabricated-fact-maersk-fine`. The reason is what the case tests, not the topic.

## Drift

Laws get amended, so a case can go stale. Each reference records a fingerprint of the text it cited when the case was stamped. `evals check` fingerprints it again and compares:

| Kind | What it means |
| ---- | ------------- |
| `unresolved` | The reference no longer resolves to any stored chunk. This eval case is now invalid |
| `stale` | The reference still exists but the cited text has changed since the case was stamped. This eval case needs to be updated |
| `unstamped` | Nothing recorded to compare against, so drift cannot be seen on this reference |

`evals check` fails on an unresolved reference, and with `--fail-on-stale` on a stale one too, as the nightly ingest runs it. `evals run` lists stale cases beside the scores but never fails on one, since only a human can repair a case.

## Stamping

Run `evals stamp` on a newly authored case, or on a stale one you have just re-reviewed against the new text. A stamp asserts that review.

Stamps, traits and fields a case leaves at their default are excluded from `dataset_sha`, so none of them breaks comparability with runs that scored the same assertions.

## Running

Each case runs, one at a time, through the same graph as `/chat` and is scored off the `ChatState` it ends in, so a run measures what production records and each timing measures one case alone.

## The no-retrieval baseline

`evals run --no-retrieval` answers every case from the model's memory alone. Only synthesize runs, with no sources and a prompt that does not ask it to decline. Set beside a normal run with `evals compare`, the correctness delta is what retrieval adds over asking the model cold.

Its retrieval and citation scores are zero by construction. Faithfulness and the gate and assess refusal rates are unmeasured, so out-of-corpus cases are scored on the judge's refusal check alone. The run records `retrieval: false`, and `evals compare` marks it "no retrieval".

## Storing runs

`evals run` stores each run's setup and `EvalMetrics` in `eval_runs`, not its per-case results, and prints its id. `--no-store` only prints it. A run records the commit it ran at, and `git_dirty` when tracked files had uncommitted edits. `evals compare BASE OTHER` prints every metric of both runs, with the other's delta from the base, then the settings the two differ on.

## Metrics

Scoring lives in `metrics.py`. The run's `EvalMetrics` groups the measures into blocks: `counts`, `retrieval`, `context`, `gate`, `assess`, `citations`, `answers`, `judge`, `latency`, `usage`.

| Metric | Scored over | What it measures |
| ------ | ----------- | ---------------- |
| `retrieval.raw_hit_rate` | in-corpus | Search found at least one authored reference |
| `retrieval.raw_recall` | in-corpus | Share of authored references search found |
| `retrieval.expanded_hit_rate` | in-corpus | At least one authored reference reached the prompt |
| `retrieval.expanded_recall` | in-corpus | Share of authored references that reached the prompt |
| `context.mean_context_chunks` | in-corpus | Context blocks the prompt carried |
| `context.mean_context_chars` | in-corpus | Context text length the prompt carried, what recall is bought with |
| `citations.cited_references` | answered in-corpus | Share of authored references the answer cited |
| `citations.markers_in_context` | answers citing anything | Share of `[n]` markers addressing a block the model was given |
| `answers.prompt_wording` | all | Answers naming the prompt's blocks to the reader ("the context", "the provided text"), a string check |
| `answers.mean_words` | answers written | Mean answer length in words, how much a prompt change trimmed or padded |
| `gate.refusal_rate` | out-of-corpus | Share the pre-model gate refused |
| `gate.false_refusals` | in-corpus | Cases the gate refused |
| `gate.refused_a_found_reference` | in-corpus | Of those, the ones where search had already found a reference |
| `assess.refusal_rate` | out-of-corpus | Share that passed the gate and assess refused |
| `assess.false_refusals` | in-corpus | Cases assess refused |
| `judge.correctness` | judged in-corpus | Share of answers stating what the reference answer states |
| `judge.faithfulness` | judged answers citing anything | Mean share of an answer's claims its cited context backs |
| `judge.refusal_rate` | judged out-of-corpus | Share that passed the gate and declined in the model's own words |
| `judge.judged` | all | Cases the judge returned a verdict on |

Expanded recall can fall below raw: expansion widens each hit into its surrounding section, and against a fixed context budget that can push a reference *out*.

## Judge

The other measures read retrieval and citations, not what the answer says. The judge in `judge/` does: a second model, set by `EVAL_JUDGE_MODEL`, grades each answered case on the dimensions that apply to it, one call per dimension.

| Dimension | Applies to | Judge sees | Judge returns |
| --------- | ---------- | ---------- | ------------- |
| Correctness | in-corpus | question, reference answer, answer | critique, then pass / fail / cannot_judge, then the failure's kind |
| Faithfulness | in-corpus answers citing a block they were given | the answer, the blocks it cited under their own markers | critique, then each claim marked supported or not |
| Refusal | out-of-corpus answers that passed the gate | question, answer | critique, then pass (declined) / fail / cannot_judge |

Verdicts are categorical at the judge and numeric only by aggregation: a pass is 1, a fail 0, faithfulness the supported share of the claims, and cannot_judge unmeasured rather than zero. The critique comes before the verdict, and `--verbose` prints it under any case the judge did not pass. A failed judge call leaves its dimension unmeasured. A run exits non-zero when the judge returns a verdict on under `EVAL_JUDGE_MIN_COVERAGE` of the answered cases, so a misnamed judge model does not pass as an unmeasured run. `--no-judge` skips the judge, and tune never judges.

Judging runs after every case has been timed, so no timing carries a judge call, with `EVAL_JUDGE_CONCURRENCY` cases judged at a time.

## Tuning

Tune measures a baseline, then re-measures once per candidate value, one factor at a time. It runs retrieval only so a sweep costs Postgres time rather than model spend. Rows are ranked by expanded recall, ties broken by the cheaper context.

The grid lives in `tune/params.py`. A param only read under another setting, like `MIN_RERANKER_RELEVANCE` under `RERANK_ENABLED`, names it in `requires` so it is measured with that setting on.

## Caching

Embed and rerank calls replay from disk under `EVAL_CACHE_DIR`, keyed on each call's own request parameters. Deleting the directory invalidates the lot.

Completions are never cached, since replayed answers would measure the cache rather than the model. A cached run's timings measure disk reads, so every run records `cached`. Use `--no-cache` for a latency baseline, or when a change alters what those calls *are*, such as a different embedding model.
