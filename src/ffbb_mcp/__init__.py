"""FFBB MCP Server — Fédération Française de Basketball."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("ffbb-mcp")
except PackageNotFoundError:
    __version__ = "unknown"
