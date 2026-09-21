"""Every ORM schema is registered so SQLAlchemy can configure its mappers."""

from pathlib import Path

import app
import app.core.db.registry  # noqa: F401

APP_DIR = Path(app.__file__).parent


def test_registry_imports_every_capability_schema_module():
    """Fails if a capability adds schemas.py at any depth without importing it in registry.py."""
    modules = {
        ".".join(path.relative_to(APP_DIR.parent).with_suffix("").parts)
        for path in APP_DIR.rglob("schemas.py")
    }
    source = (APP_DIR / "core" / "db" / "registry.py").read_text()
    assert "app.ingestion.chunk.schemas" in modules
    assert not {name for name in modules if name not in source}
