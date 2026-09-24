"""Context blocks: every kind of numbered block a citation marker can address."""

from collections.abc import Sequence
from typing import Annotated

from pydantic import Field

from app.mrv.models import MrvBlock
from app.retrieval.models import RetrievedChunk

ContextBlock = Annotated[RetrievedChunk | MrvBlock, Field(discriminator="source")]
"""A numbered block, tagged by source so a cached answer loads back as the right kind."""


def corpus_chunks(blocks: Sequence[ContextBlock]) -> list[RetrievedChunk]:
    """The blocks that are corpus chunks, for code that reads acts and divisions."""
    return [block for block in blocks if isinstance(block, RetrievedChunk)]
