"""What the formula model answers for an image, and what parse counted of them per document."""

from app.core.models import FrozenModel


class FormulaReading(FrozenModel):
    """One image as the formula model read it: LaTeX when it is a formula, None when not."""

    is_formula: bool
    latex: str | None = None


class ImageCounts(FrozenModel):
    """Images parse read from the formula model, and ones the cache already held."""

    read: int = 0
    reused: int = 0
