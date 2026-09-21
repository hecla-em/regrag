# AGENTS.md

- Do not preserve backward compatibility. Remove obsolete paths instead of
  adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current
  requirements. Avoid speculative abstractions, configuration, and
  indirection.
- Grow the system in layers. Start from the smallest version that works end
  to end, and add each new capability on top of a product that already
  works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall
  complexity or improve reliability. Do not reimplement common
  functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own
  implementation or adding packages. Do not assume a library lacks a
  capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap
  that only works for now and is meant to be replaced later.
- Do not write inline comments. Prefer self-describing code; where
  explanation is genuinely needed, use a docstring of 1-2 lines max.
- Write a unit test only for complex, specific logic: a parser, reference
  extraction, ranking, metric maths, stream reduction. Write it as one table
  of inputs to outputs, not a function per case.
- Cover everything else through a real seam: the route, the compiled graph,
  real Postgres and Redis, with only the providers faked. A new feature
  usually adds a scenario to an existing integration test, not a new file.
- Never test a constant, a prompt's wording, a default, an enum value, an
  error message, a library's behaviour (pydantic, SQLAlchemy, FastAPI,
  tenacity, argparse, litellm), or that a mock was called.
- Never add to a README unasked. The prose there is curated; ask first,
  and take no for an answer. Design rationale belongs in the commit
  message or a 1-2 line docstring, not a new README paragraph.
