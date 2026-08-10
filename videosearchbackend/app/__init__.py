"""VideoSearch backend application package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("videosearchbackend")
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0"
