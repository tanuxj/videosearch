"""Single import point for Alembic.

Autogenerate only sees tables registered on `Base.metadata` at import time,
so every feature package that owns tables must be imported here. Add one
line per feature as they land.
"""

from app.auth import models as auth_models  # noqa: F401  (registers tables)
from app.db.base import Base

__all__ = ["Base"]
