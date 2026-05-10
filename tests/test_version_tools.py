import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_version_alignment = _load_tool("check_version_alignment")
sync_version = _load_tool("sync_version")


def test_sync_version_updates_all_checked_docs(tmp_path: Path):
    root = tmp_path
    (root / "docs").mkdir()
    (root / "website-docs" / "reference").mkdir(parents=True)

    for path in [
        root / "docs" / "TOOLS_REFERENCE.md",
        root / "website-docs" / "reference" / "tools.md",
    ]:
        path.write_text(
            '> Version courante : **1.2.0**\n{"package_version": "1.2.0"}\n',
            encoding="utf-8",
        )

    sync_version.update_docs(root, "1.2.1")

    for path in [
        root / "docs" / "TOOLS_REFERENCE.md",
        root / "website-docs" / "reference" / "tools.md",
    ]:
        content = path.read_text(encoding="utf-8")
        assert "> Version courante : **1.2.1**" in content
        assert '"package_version": "1.2.1"' in content


def test_sync_version_covers_alignment_checked_paths():
    checked_paths = set(
        match.group(1)
        for match in check_version_alignment.re.finditer(
            r'_check_contains\(\s*"([^"]+)"',
            Path(check_version_alignment.__file__).read_text(encoding="utf-8"),
        )
    )
    sync_source = Path(sync_version.__file__).read_text(encoding="utf-8")

    for path in checked_paths:
        if path == "website/index.html":
            continue
        for part in Path(path).parts:
            assert part in sync_source
