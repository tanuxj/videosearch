from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.core.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    # False when the app runs in open-access mode: no signup, no login, every
    # request served as the shared guest account.
    auth_enabled: bool


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the API health status and current environment.",
)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.app_env,
        auth_enabled=settings.auth_enabled,
    )
