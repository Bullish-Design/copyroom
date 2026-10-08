"""CopyRoom CLI for local Templateer sources and jj project workflows."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("copyroom")
except PackageNotFoundError:
    __version__ = "0+unknown"
