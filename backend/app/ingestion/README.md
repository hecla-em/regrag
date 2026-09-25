# Ingestion
This module builds the corpus: it works out which EU acts belong in it, downloads them, and stores them as chunks and vectors for the retrieval stage to query.

```bash
uv run ingest             # every seed topic
uv run ingest fueleu      # one topic
```

Re-running is cheap and safe: unchanged documents are neither downloaded nor re-embedded. After the corpus, the same command loads any THETIS-MRV emissions file EMSA has published since the last run (`app/mrv/`).

Discovery runs twice, first for the topics and then for the acts their chunked text cites (4.3). After each pass, fetch, parse and chunk run one document at a time, each committed before the next begins, so peak memory stays flat and a run that dies keeps the work it already did. Pruning and embedding run once at the end, because both need to see the corpus whole.

## 1 Discover
Discovery answers two questions: which documents belong in the corpus, and which version of each to download.

### 1.1 CELEX
Every document in EUR-Lex is identified by a CELEX number and this can be used to find related law documents and versions.

```
3 2023 R 1805
│ │    │ └── act number within that year
│ │    └──── kind: R regulation, L directive, D decision
│ └───────── year of adoption
└─────────── sector: 3 is legislation
```

**Which documents belong in the corpus?**
Sector 3 with a kind letter of R, L or D which means binding legislation. Anything else is discarded — sector 5, for instance, covers the notices, opinions and Commission papers that reference a law without imposing obligations.

**Which version of each?**
An act and its amended versions have matching ids apart from the sector digit and date suffix. The original sits in sector 3 with each consolidation under sector 0 with that date appended.

```
32023R1805              FuelEU as published
02023R1805-20230922     consolidated to 22 September 2023
```

When an act is absorbed into another, its consolidations are filed under the absorbing act's id instead. An act whose consolidations are all filed under another id has been superseded, and the act that absorbed it is the one to fetch.

### 1.2 Finding the corpus
Discovery produces the list of CELEX ids to download. The corpus is built around three acts: FuelEU (`32023R1805`), MRV (`32015R0757`) and the ETS Directive (`32003L0087`).

The EU Publications Office runs a document metadata database, CELLAR, which is queried for every act naming one of those acts as its legal basis (the law it was made under) along with the acts themselves.

The results are wider than the corpus, so each act must pass three filters:

- it is legislation: sector 3, with a kind of R, L or D
- it is still in force
- it has not been superseded by an act that absorbed it

FuelEU and MRV are shipping laws from end to end, so every act that passes belongs. The ETS Directive is the whole carbon market: 223 acts name it as their legal basis and 56 pass the filters, most of them on aviation, the registry or free allocation. CELLAR also records which article of the base act each one was adopted under, written as `A03gfP4` for Article 3gf(4), and a topic can name the articles it keeps and the ones it turns away:

- ETS keeps the acts adopted under Articles 3ga to 3gg, the shipping chapter, and under the 12(3-b) to 12(3-e) derogations for ice-class ships, small islands and outermost regions.
- ETS turns away the acts adopted under Article 3gf(2), the lists of shipping companies and their administering authorities: 200k characters of names that crowd the rules out of retrieval.

That leaves the Directive itself and three acts made under it.

CELLAR also reports every consolidated version it holds, and those filed under the act's own id are carried forward, newest first, as the versions to try downloading.

CELLAR also supplies each act's official English title, which is copied onto its chunks so the chat can name an act as the law does rather than by its CELEX number.

### 1.3 Losing documents
Discovery refuses a result set that has lost more than a fifth of the acts the previous run held, and at least three of them: a truncated SPARQL response and a mass repeal look identical from here, and only one of them should empty the corpus.

## 2 Fetch
Fetch turns discovery's list into stored bytes, and avoids the download wherever it can.

### 2.1 Download
Each document is downloaded from CELLAR, because EUR-Lex's own HTML endpoint sits behind a bot challenge that only a browser can pass.

A CELEX id is enough to locate a document, and the request asks for the English XHTML, the same markup EUR-Lex shows.

```
https://publications.europa.eu/resource/celex/32023R1805
Accept: application/xhtml+xml
Accept-Language: eng
```

HTML is preferred over PDF because it carries articles, paragraphs and tables as markup.

Download tries those consolidated versions newest first, then the original act. Not every id has text behind it: CELLAR mints a consolidated id when an act is published but serves no text until one is amended in.

Documents are stored as objects, files on disk in dev, a Cloudflare R2 bucket in prod, keyed by act, version and a hash of the bytes:

```
{act}/{version downloaded}/{sha256 of the bytes}.html
32023R1805/32023R1805/9f86d081….html      FuelEU, served as published
```

A new consolidation is a new object, not a replacement, so every earlier run's row still points at the bytes it read and hashed.

### 2.2 Re-fetching
Fetch compares the versions discovery offers against those it offered the run that stored the document, so an unchanged document is not downloaded or written again. The comparison is on version ids, not text, since a new consolidation is a new id.

Reusing a version means reading its stored bytes. Bytes that are missing, or that no longer hash to what the row recorded, count as bytes we do not have, and the version is downloaded again. A store that cannot be read at all fails the document rather than sending the whole corpus back to CELLAR.

### 2.3 Where the bytes go
`STORAGE_BACKEND` decides where a downloaded document is written. It defaults to `local`, putting files under `RAW_DATA_DIR` (`<repo>/data/raw`), so dev and tests need no network and no bucket. Set it to `r2` and fill in the `R2_*` settings to write to the Cloudflare bucket instead.

## 3 Parse
Parse turns each downloaded page into a structure: the articles, paragraphs and annexes the document is made of.

### 3.1 Source documents
The HTML comes in two flavours, depending on which version was downloaded. An act as published in the Official Journal uses one set of CSS class names and a consolidated act another. The same article heading in each:

```html
<p class="oj-ti-art">Article 6</p>           <!-- as published -->
<p class="title-article-norm">Article 6</p>  <!-- consolidated -->
```

### 3.2 Section tree
A regulation is already a nested document. Articles contain numbered paragraphs, and annexes contain headings, prose and tables:

```
Regulation
├── Article 1
│   ├── paragraph 1
│   └── paragraph 2
└── Annex I
    ├── heading
    └── table
```

Parse keeps that nesting, because it is what later lets a chunk know it is Article 6(2).

The HTML nests the same way, so parse reads down the page and records each article, paragraph and annex as it recognises it:

```html
<div class="eli-subdivision" id="art_6">
  <p class="oj-ti-art">Article 6</p>
  <div id="006.001"><p>1. Ships shall ...</p></div>
  <div id="006.002"><p>2. The Commission shall ...</p></div>
</div>
```

becomes:

```
Article 6
├── paragraph 1 — "Ships shall ..."
└── paragraph 2 — "The Commission shall ..."
```

The dialects disagree about more than class names. An as-published paragraph carries its number as a leading `1.` in its own text, where a consolidated one keeps it in a marker beside the text. Consolidated annexes nest under levelled sub-headings where as-published ones are flat. Each dialect declares those differences and hands them to one shared procedure.

### 3.3 Output
At the end of parsing, only the operative text (articles and annexes) remains. Everything else on the page is dropped:

- **Recitals**, because consolidation strips them — FuelEU has 72 and consolidated MRV none, so keeping them would cover some acts deeply and others not at all.
- **Footnotes and amendment markers** (`▼M2`), which are citation apparatus and change tracking rather than law. The text the markers wrap is kept.
- **Table scaffolding**. Most tables exist only to indent a list (260 in FuelEU against 13 holding real data), so their structure is discarded and the text flattened into the surrounding paragraph. Genuine data tables are kept as a grid.
- **Formulas**, which the XHTML only draws as images. Parse takes each from the act's Formex, EUR-Lex's XML, where it is markup, and writes it in as LaTeX. A formula Formex also only has as an image stays a `[formula]` placeholder.

## 4 Chunk
Chunking splits the parsed document into the sections to be retrieved by the agent. The goal is to make a chunk short enough to embed, complete enough to read on its own and specific enough to cite.

### 4.1 Boundaries
Rather than slide a fixed window over the text, each leaf of the section tree becomes one chunk: a numbered paragraph, a data table, a block of annex prose.

The few leaves over the 2,000-character cap are split at the best boundary available: a line break first, a sentence inside an over-long line, and a blunt character cut only where neither exists. Each piece records that it is part 2 of 3, so a fragment can be recognised as one.

Tables split on row boundaries and repeat the header row on every piece, so no row is left without its column names.

### 4.2 Locators
Each chunk also stores its location, such as *Article 6(2) of FuelEU*, inherited from everything above it in the section tree.

```
Article 6  "Additional zero-emission requirements for energy used at berth"
└── paragraph 2   →   article 6, paragraph 2   →   cited as "Article 6(2)"
```

That address lets a reader check an answer against the law, and lets a cross-reference be followed by lookup (4.3).

### 4.3 Cross-references
Legislation often makes references to other documents or other sections of the current document. These citations are stored as structured fields alongside the text:

```
"... in accordance with Article 25(2) of Directive (EU) 2018/2001"
   →  instrument 32018L2001, article 25, paragraph 2
```

An article named on its own belongs to the document it sits in. One qualified by an instrument takes that instrument's CELEX id, so it can be matched against the rest of the corpus.

A point or subparagraph named between the article and its instrument — `Article 3, point (e), of Regulation (EU) 2015/757`, the form a definitions article borrows a term in — still qualifies the article by that instrument. The point is stored with the reference, and each chunk records the points its text opens lines with, so a follow by point is a lookup.

References to the same document always land. One to another act lands only if that act is in the corpus, so once the topics are chunked, discovery makes a second pass for every act their text cites an article or annex of. That is how Directive 2018/2001, the most-cited act and where fuel certification is defined, gets in. The hop goes one step: a cited act's own citations are not followed, and a cited act that fails to store does not fail the run.

### 4.4 Chunk identity
A chunk is addressed by a hash of its text and locator rather than its position in the document. Reconciling is then a set difference: new hashes inserted, missing ones deleted, the rest keep the vectors they already have, so a re-run over an unchanged corpus costs nothing to embed.

Deletion is the irreversible half, so pruning waits until every document has been through the loop, and runs only when fetch and parse succeeded for every topic document — a failed run cannot tell absence from failure.

A document that chunks to nothing is failed rather than reconciled, because reconciling an empty set would delete its stored rows. Markup can parse cleanly and still yield nothing, as when every article is only a heading.

## 5 Embed
Embedding turns each chunk into a vector, so that retrieval can find a provision (a piece of law) by what it means rather than by the words it happens to use.

Embedding sweeps whatever has no vector yet, rather than only what this run chunked, so an interrupted run, a provider outage or a failed batch repairs itself on the next run with no resumption state to track. The sweep reads a page at a time, embeds a few batches at once and commits each batch as it lands.

### 5.1 Hybrid search
Each chunk is indexed twice: once as a vector, and once as keywords the database builds from its own columns, weighting citation and title above body text so a query mentioning Article 6 favours the chunk that *is* Article 6.

Neither is sufficient alone: keywords cannot match *plug in at berth* to *on-shore power supply*, and vectors cannot be trusted to tell Article 6 from Article 16.

## 6 Runs
Every ingest is recorded as a run. Each stage reports what it added, changed, left alone and failed on, and that report is stored on the run row rather than only printed, so a run can be accounted for after the fact.

A document that fails one stage does not abort the run: the failure is recorded against its CELEX id, the remaining documents carry on, and the run itself closes as failed. A run that dies outright — a provider outage, a Ctrl-C, an out-of-memory kill — closes as aborted instead. Neither status stands for a corpus: only a successful run tells later runs that its documents are the whole of its topic. Every finished run is stamped with a corpus version, the date the corpus last changed plus a fingerprint of it, so an unchanged re-run keeps its version. It also records the chunk count and average chunk length that keyword ranking reads.

A run in progress is visible: until it finishes, a reader sees some acts at their new version and some at the old. The corpus version is stamped only at the end, so anything keyed on it still flips in one step.
