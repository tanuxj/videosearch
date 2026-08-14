"""Single import point for Alembic.

Autogenerate only sees tables registered on `Base.metadata` at import time,
so every feature package that owns tables must be imported here. Add one
line per feature as they land.
"""

from app.auth import models as auth_models  # noqa: F401  (registers tables)
from app.db.base import Base
from app.history import models as history_models  # noqa: F401  (registers tables)
from app.videos import models as videos_models  # noqa: F401  (registers tables)

__all__ = ["Base"]
