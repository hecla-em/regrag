# Evals

This module focuses on the evaluation of the graph against a set of authored cases stored in `dataset/golden.json`.

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

A case is one of two kinds. An `in_corpus` case is scored on what retrieval found and what the answer cited, so it needs both an answer and references. An `out_of_corpus` case asks something the corpus does not cover and is scored on refusal alone.

### Traits

The kind says how a case is scored. What a case *tests* is a separate list, `traits`, which changes no scoring and which a case may hold several of:

| Trait | What the question demands |
| ----- | ------------------------- |
| `multi_hop` | The answer sits a chain of citations away from where search lands: the landing article defines a term by pointing at another act, or names a procedure it leaves to an implementing act |
| `multi_part` | The question asks more than one thing in one sentence, so each part needs its own retrieval |

A run, tune or stamp can select on a trait with `--trait multi_part`, on a kind with `--kind out_of_corpus`, or on an id substring with `--case fueleu`; the three narrow together. Traits are left out of the dataset hash, so marking a case does not break comparability with the runs that scored it before.

### Ids

An id reads like a test name: what would have to break for the case to fail. Kind and traits are fields, so neither appears in the id.

- An in-corpus id is `<area>-<what it asks>`: `fueleu-borrowing-limits`, `mrv-verification-report`.
- An out-of-corpus id is `<why the corpus cannot answer>-<what it asks>`: `unrelated-topic-airline-luggage`, `adjacent-regime-imo-cii-rating`, `fabricated-fact-maersk-fine`. The topic is incidental; the reason is what the case tests.

## Drift

A problem the dataset faces is that laws get amended which may render some of our eval cases as stale. To track this drift, each reference also records a fingerprint of the text that was there when the case was written. `evals check` fingerprints it again and compares:

| Kind | What it means |
| ---- | ------------- |
| `unresolved` | The reference no longer resolves to any stored chunk. This eval case is now invalid |
| `stale` | The reference still exists but the cited text has changed since the case was stamped. This eval case needs to be updated |
| `unstamped` | Nothing recorded to compare against, so drift cannot be seen on this reference |

`evals run` reports the stale cases alongside the scores, but never fails on one: repairing a case means a human re-reading the new text. The check covers the whole dataset, so `--case` narrows what is scored, not what is checked for drift.

## Stamping

`evals stamp` records what the cited text says now. Run it on a newly authored case, or on a stale one you have just re-reviewed against the new text. The stamp asserts that the dataset has been reviewed. `--case` stamps a subset.

Stamps and fields a case leaves at their default are excluded from `dataset_sha`, so neither re-stamping a case nor adding an optional field breaks comparability with runs that scored the same assertions before it.

## Running

Each case is driven through the same graph the `/chat` endpoint runs, and ends in the same `ChatState` a real request ends in, so a run is scored off what production records rather than off a parallel eval path. Cases run one at a time, so a per-case timing measures that case alone.

## The no-retrieval baseline

`evals run --no-retrieval` answers every case from the model's memory alone. Only synthesize runs, with no sources, under a prompt that swaps the context and citation rules for "answer from what you know, and name the act and article", with no instruction to decline. Set beside a normal run with `evals compare`, the correctness delta is what retrieval adds over asking the model cold.

The retrieval and citation scores of such a run are zero by construction, and faithfulness is unmeasured, since there is no context to be faithful to. Out-of-corpus cases never meet the gate, so they are scored on the judge's refusal check alone. The run records `retrieval: false`, and `evals compare` marks it "no retrieval" in its header.

## Storing runs

`evals run` stores each run in `eval_runs` and prints its id. `--no-store` only prints it. A stored run keeps its setup and its `EvalMetrics`, not its per-case results. It records the commit it ran at, and `git_dirty` when tracked files had uncommitted edits, so a score can be traced to the code behind it. Outside a checkout, as in the image, the commit is left empty. Settings and metrics are JSONB, since both grow with the config and the metrics. `evals compare BASE OTHER` prints every metric of both runs, with the other's delta from the base, then the settings the two differ on.

## Metrics

Scoring lives in `metrics.py`, each measure a plain function over the run's results. The run's `EvalMetrics` groups them into blocks — `counts`, `retrieval`, `context`, `gate`, `assess`, `citations`, `judge`, `latency`, `usage`. A retrieval-only tune run fills the same model and leaves the blocks past the model call unmeasured.

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
| `gate.refusal_rate` | out-of-corpus | Share the pre-model gate refused |
| `gate.false_refusals` | in-corpus | Cases the gate refused |
| `gate.refused_a_found_reference` | in-corpus | Of those, the ones where search had already found a reference |
| `assess.refusal_rate` | out-of-corpus | Share that passed the gate and assess refused |
| `assess.false_refusals` | in-corpus | Cases assess refused |
| `judge.correctness` | judged in-corpus | Share of answers stating what the reference answer states |
| `judge.faithfulness` | judged answers citing anything | Mean share of an answer's claims its cited context backs |
| `judge.refusal_rate` | judged out-of-corpus | Share that passed the gate and declined in the model's own words |
| `judge.judged` | all | Cases the judge returned a verdict on |

The raw and expanded pairs are worth reading together. Expansion widens each hit into its surrounding section, and against a fixed context budget that can push a reference *out*, so expanded recall is not guaranteed to be the higher of the two.

## Judge

Every measure above the judged rows reads retrieval and citation plumbing; none reads what the answer says. The judge in `judge/` is the measure that does: a second model, set by `EVAL_JUDGE_MODEL` and deliberately not the one that wrote the answer, grades each answered case on the dimensions that apply to it, one model call per dimension.

| Dimension | Applies to | Judge sees | Judge returns |
| --------- | ---------- | ---------- | ------------- |
| Correctness | in-corpus | question, reference answer, answer | critique, then pass / fail / cannot_judge, then the failure's kind |
| Faithfulness | in-corpus answers citing a block they were given | the answer, the blocks it cited under their own markers | critique, then each claim marked supported or not |
| Refusal | out-of-corpus answers that passed the gate | question, answer | critique, then pass (declined) / fail / cannot_judge |

Verdicts are categorical at the judge and numeric only by aggregation: a pass is 1, a fail 0, faithfulness the supported share of the claims, and cannot_judge unmeasured rather than zero. The critique is written before the verdict, so the reasoning is on the page before the verdict is decided; `--verbose` prints it under any case the judge did not pass. A judge call that fails leaves its dimension unmeasured and the run green; a run asked to judge that gets no verdict on any answered case exits non-zero and says so, so a misnamed judge model does not pass as an unmeasured run. The run records `judged`, whether the judge was on, beside `cached`. `--no-judge` skips the judge, for a retrieval baseline that costs no model spend; tune never judges.

Judging is a pass over the run once every case has been timed, so no case's timing carries a judge call; cases are judged `EVAL_JUDGE_CONCURRENCY` at a time, and an in-corpus answer's correctness and faithfulness calls run together.

## Tuning

Tune measures a baseline, then re-measures once per candidate value, one factor at a time. It runs retrieval only so a sweep costs Postgres time rather than model spend. Rows are ranked by expanded recall, ties broken by the cheaper context.

The grid of parameters is stored in `tune/params.py`. Because some parameters, like `MIN_RERANKER_RELEVANCE` are dependent on the reranker being enabled, there is a `requires` field to ensure that this is applied even if the baseline doesn't have it.

## Caching

Embed and rerank calls replay from disk under `EVAL_CACHE_DIR`, keyed on each call's own request parameters. The first run over a case pays for them and every run after it does not. Deleting the directory invalidates the lot.

Synthesis is deliberately not cached as a run replaying its own answers would measure the cache rather than the model. Cached timings measure a disk read where a provider call would be, so `cached` is recorded on every run to keep the two from being compared. Use `--no-cache` for a latency baseline, or when a change alters what those calls *are*, such as a different embedding model.
