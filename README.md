# RegRag

[![CI](https://github.com/hecla-em/regrag/actions/workflows/ci.yml/badge.svg)](https://github.com/hecla-em/regrag/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Ask a question about EU maritime emissions law and get an answer drawn from the
regulations themselves, with the article behind each claim cited.

![The RegRag chat page, ready for a question](docs/images/hero.png)

Shipping companies trading in Europe now answer to three EU emissions laws:

- The [MRV Regulation](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32015R0757)
  (2015/757) makes them monitor, report and verify each ship's emissions.
- The [FuelEU Maritime Regulation](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R1805)
  (2023/1805) limits the greenhouse gas intensity of the energy a ship uses.
- The [EU ETS Directive](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32003L0087)
  (2003/87/EC) has covered shipping since 2024. Companies surrender
  allowances for the emissions verified under MRV.

RegRag covers all three, plus the delegated and implementing acts made under
them. For the ETS Directive that means the acts adopted under its shipping
articles, not the rest of the carbon market. The text is long, amended often,
and cross-references itself constantly. RegRag keeps a
current copy of that corpus and answers questions against it, returning the
exact articles it relied on rather than a paraphrase to take on trust.

## How it works

- **Discovery** queries CELLAR for every act with FuelEU, MRV or the ETS
  Directive as its legal basis, then resolves each to its latest consolidated
  version by CELEX number.
- **Ingestion** runs nightly. It downloads each act from CELLAR, parses it into
  its articles, paragraphs and annexes, and stores each paragraph as a chunk
  that knows its own citation (*Article 6(2) of FuelEU*) and the articles it
  refers to. Chunks are embedded and keyword-indexed. An unchanged document is
  neither re-downloaded nor re-embedded, so keeping the corpus current is cheap.
- **Retrieval** fuses a vector leg and a BM25 text leg with Reciprocal Rank
  Fusion inside one SQL query, then reranks with a cross-encoder. Stored
  cross-references let a hit be followed to the article it cites.
- **Answering** lets the model search again or follow a cited article, then
  streams an answer marking each claim with the block it came from. A question
  the corpus does not cover is refused rather than answered from memory.
- **Evaluation** scores a golden dataset of authored questions through the same
  graph the API runs: what retrieval found, what the answers cited, and what
  the refusal gate caught.

Each stage lives in its own package, documented where it is implemented:

| Directory                                                | Contents                                                        |
| -------------------------------------------------------- | --------------------------------------------------------------- |
| [`backend/app/ingestion/`](backend/app/ingestion/README.md) | Discovery through embedding: how the corpus is built            |
| [`backend/app/retrieval/`](backend/app/retrieval/README.md) | Hybrid search and exact article lookup: how it is searched      |
| [`backend/app/chat/`](backend/app/chat/README.md)           | The answering graph and its SSE endpoint                        |
| [`backend/app/evals/`](backend/app/evals/README.md)         | The golden dataset and the runner that scores the graph on it   |
| [`frontend/`](frontend/)                                    | User interface (React, TanStack, Tailwind)                      |

Setup and commands are in [`backend/README.md`](backend/README.md) and [`frontend/`](frontend/).
