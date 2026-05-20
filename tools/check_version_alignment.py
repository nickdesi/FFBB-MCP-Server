"""Check project version consistency across metadata and public docs."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _project_version() -> str:
    data = tomllib.loads(_read("pyproject.toml"))
    return str(data["project"]["version"])


def _check_contains(path: str, needle: str, description: str) -> list[str]:
    if needle in _read(path):
        return []
    return [f"{path}: missing {description}: {needle!r}"]


def _check_tag(version: str) -> list[str]:
    github_ref = re.sub(r"^refs/tags/", "", sys.argv[1] if len(sys.argv) > 1 else "")
    if not github_ref:
        return []
    expected = f"v{version}"
    if github_ref == expected:
        return []
    return [f"git tag mismatch: expected {expected!r}, got {github_ref!r}"]


def main() -> int:
    version = _project_version()
    errors: list[str] = []

    errors += _check_contains(
        "README.md",
        f"https://img.shields.io/badge/version-{version}-green?style=for-the-badge",
        "README version badge",
    )
    errors += _check_contains(
        "website/index.html",
        f'"softwareVersion": "{version}"',
        "website softwareVersion",
    )
    errors += _check_contains(
        "website/index.html", f">V{version} Stable<", "website visible badge"
    )
    errors += _check_contains(
        "website-docs/reference/tools.md",
        f"> Version courante : **{version}**",
        "website docs version header",
    )
    errors += _check_contains(
        "website-docs/reference/tools.md",
        f'"package_version": "{version}"',
        "website docs ffbb_version example",
    )
    errors += _check_tag(version)

    if errors:
        print("Version alignment check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Version alignment OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
