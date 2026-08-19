"""Check project version consistency across metadata, docs, and git tags."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _project_version() -> str:
    data = tomllib.loads(_read("pyproject.toml"))
    return str(data["project"]["version"])


def _latest_git_tag() -> str | None:
    """Return the latest semver tag in the repo, or None."""
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*", "--sort=-version:refname"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    except FileNotFoundError:
        pass
    return None


def _check_contains(path: str, needle: str, description: str) -> list[str]:
    if needle in _read(path):
        return []
    return [f"{path}: missing {description}: {needle!r}"]


def _check_tag(version: str, explicit_tag: str | None = None) -> list[str]:
    """Check version matches an explicit tag arg, or the latest git tag."""
    errors: list[str] = []

    # Priority 1: explicit tag argument (release workflow)
    if explicit_tag:
        expected = f"v{version}"
        if explicit_tag != expected:
            errors.append(
                f"git tag mismatch: pyproject={version!r}, tag={explicit_tag!r}"
            )
        return errors

    if os.environ.get("SKIP_TAG_CHECK") == "1":
        return errors

    # Priority 2: compare with latest git tag (CI on main / PR)
    latest = _latest_git_tag()
    if latest:
        tag_version = latest.lstrip("v")
        if tag_version != version:
            errors.append(
                f"version drift: pyproject.toml={version!r} but latest git tag={latest!r}. "
                f"Run 'uv run python tools/sync_version.py' to align."
            )

    return errors


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
        "website-docs/reference/tools.md",
        f"> Version courante : **{version}**",
        "website docs version header",
    )
    errors += _check_contains(
        "website-docs/reference/tools.md",
        f'"package_version": "{version}"',
        "website docs ffbb_version example",
    )

    explicit_tag = re.sub(r"^refs/tags/", "", sys.argv[1] if len(sys.argv) > 1 else "")
    errors += _check_tag(version, explicit_tag=explicit_tag or None)

    if errors:
        print("Version alignment check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Version alignment OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
