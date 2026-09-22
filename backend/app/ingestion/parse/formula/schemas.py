"""Parse's formula cache: one row per distinct inline image."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.schema import BaseSchema


class FormulaRendering(BaseSchema):
    """What FORMULA_MODEL read in one image: its LaTeX, or NULL where it is not a formula.
    model names who read it, so a model change re-reads the rows made by the old one."""

    __tablename__ = "formula_renderings"

    image_hash: Mapped[str] = mapped_column(String(16), primary_key=True)
    latex: Mapped[str | None]
    model: Mapped[str]
