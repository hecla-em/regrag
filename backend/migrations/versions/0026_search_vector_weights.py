"""search vector weights

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-22 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SEARCH_VECTOR_SQL = (
    """setweight(to_tsvector('english', citation || ' ' || coalesce(title, '')), 'A')"""
    """ || setweight(to_tsvector('english', "text"), 'B')"""
)
NEW_SEARCH_VECTOR_SQL = (
    """setweight(to_tsvector('english', citation), 'A')"""
    """ || setweight(to_tsvector('english', coalesce(title, '')), 'B')"""
    """ || setweight(to_tsvector('english', "text"), 'C')"""
)


def _rebuild(expression: str) -> None:
    """A generated column's expression cannot be altered, so the column and its index are
    dropped and recreated; Postgres rewrites every row on the way."""
    op.drop_index("ix_document_chunks_search_vector", table_name="document_chunks")
    op.drop_column("document_chunks", "search_vector")
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN search_vector tsvector "
        f"GENERATED ALWAYS AS ({expression}) STORED"
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def upgrade() -> None:
    """Citation alone at A, so a lexeme's weight says whether it came from the citation."""
    _rebuild(NEW_SEARCH_VECTOR_SQL)


def downgrade() -> None:
    _rebuild(OLD_SEARCH_VECTOR_SQL)
