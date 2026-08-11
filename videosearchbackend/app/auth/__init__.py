"""Authentication feature package.

Everything auth-related lives here — models, schemas, hashing/JWT
primitives, business logic, dependencies and routes — so the feature can be
read (or replaced) in one place.

    models.py    users + refresh_tokens tables
    schemas.py   request/response contracts
    security.py  password hashing, JWT encode/decode, token generation
    service.py   signup / login / refresh / logout logic
    deps.py      DbSession and CurrentUser dependencies
    routes.py    the HTTP layer
"""

from app.auth.deps import CurrentUser, DbSession, get_current_user
from app.auth.models import RefreshToken, User
from app.auth.routes import router

__all__ = [
    "CurrentUser",
    "DbSession",
    "RefreshToken",
    "User",
    "get_current_user",
    "router",
]
