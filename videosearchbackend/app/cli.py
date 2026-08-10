"""Command-line entry point: `uv run videosearch-api [--reload]`."""

import argparse

import uvicorn

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="videosearch-api")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload on code changes (development).",
    )
    args = parser.parse_args()

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
