import datetime
import re
import subprocess
import sys
from pathlib import Path


def get_current_version(pyproject_path):
    content = pyproject_path.read_text("utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, flags=re.MULTILINE)
    if not match:
        raise ValueError("Version not found in pyproject.toml")
    return match.group(1)


def get_client_version(root_dir):
    lock_path = root_dir / "uv.lock"
    if not lock_path.exists():
        return None
    content = lock_path.read_text("utf-8")
    # Search for ffbb-api-client-v3 version in lockfile
    # Pattern: [[package]]\nname = "ffbb-api-client-v3"\nversion = "X.Y.Z"
    match = re.search(
        r'\[\[package\]\]\s+name\s*=\s*"ffbb-api-client-v3"\s+version\s*=\s*"([^"]+)"',
        content,
        flags=re.DOTALL,
    )
    return match.group(1) if match else None


def update_readme(root_dir, version, client_version):
    readme_path = root_dir / "README.md"
    if not readme_path.exists():
        return
    content = readme_path.read_text("utf-8")

    # 1. Update badge
    content = re.sub(
        r'(<img src="https://img.shields.io/badge/version-)[^ ]+(-green\?style=for-the-badge" alt="Version" />)',
        f"\\g<1>{version}\\g<2>",
        content,
    )

    # 2. Update update date
    now = datetime.datetime.now(datetime.timezone.utc)
    months_fr = [
        "",
        "Janvier",
        "Février",
        "Mars",
        "Avril",
        "Mai",
        "Juin",
        "Juillet",
        "Août",
        "Septembre",
        "Octobre",
        "Novembre",
        "Décembre",
    ]
    nice_date = f"{now.day} {months_fr[now.month]} {now.year}"
    content = re.sub(
        r"(Dernière mise à jour\s*:\s*)[0-9]+\s+[\wÀ-ÿ]+\s+[0-9]+",
        f"\\g<1>{nice_date}",
        content,
    )

    # 3. Update client version if found
    if client_version:
        content = re.sub(
            r"(Propulsé par <a href=\"https://pypi.org/project/ffbb-api-client-v3/\">ffbb-api-client-v3 v)[^\s<]+(</a>)",
            f"\\g<1>{client_version}\\g<2>",
            content,
        )

    readme_path.write_text(content, "utf-8")
    print(f"✅ Updated README.md (v{version}, client v{client_version or 'unknown'})")


def update_docs(root_dir, version):
    docs_path = root_dir / "docs" / "TOOLS_REFERENCE.md"
    if not docs_path.exists():
        return
    content = docs_path.read_text("utf-8")
    # Update version header
    content = re.sub(
        r"(> Version courante : \*\*)[^*]+(\*\*)", f"\\g<1>{version}\\g<2>", content
    )
    # Update example package_version (lines like "package_version": "1.1.0")
    content = re.sub(
        r'("package_version":\s*")[^"]+(")', f"\\g<1>{version}\\g<2>", content
    )
    docs_path.write_text(content, "utf-8")
    print(f"✅ Updated docs/TOOLS_REFERENCE.md (v{version})")


def update_website(root_dir, version):
    index_path = root_dir / "website" / "index.html"
    if not index_path.exists():
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    iso_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    months_fr = [
        "",
        "Janvier",
        "Février",
        "Mars",
        "Avril",
        "Mai",
        "Juin",
        "Juillet",
        "Août",
        "Septembre",
        "Octobre",
        "Novembre",
        "Décembre",
    ]
    nice_date = f"{now.day} {months_fr[now.month]} {now.year}"

    content = index_path.read_text("utf-8")
    content = re.sub(
        r'("softwareVersion":\s*")[^"]+(")', f"\\g<1>{version}\\g<2>", content
    )
    content = re.sub(
        r'("dateModified":\s*")[^"]+(")', f"\\g<1>{iso_date}\\g<2>", content
    )
    content = re.sub(
        r"(Dernière mise à jour du contenu\s*:\s*)[0-9]+\s+[\wÀ-ÿ]+\s+[0-9]+",
        f"\\g<1>{nice_date}",
        content,
    )
    content = re.sub(
        r'(<div class="badge">V)[^ ]+( Stable</div>)', f"\\g<1>{version}\\g<2>", content
    )

    index_path.write_text(content, "utf-8")

    sitemap_path = root_dir / "website" / "sitemap.xml"
    if sitemap_path.exists():
        s_content = sitemap_path.read_text("utf-8")
        s_content = re.sub(
            r"(<lastmod>)[^<]+(</lastmod>)",
            f"\\g<1>{now.strftime('%Y-%m-%d')}\\g<2>",
            s_content,
        )
        sitemap_path.write_text(s_content, "utf-8")

    print(f"✅ Updated website metadata (v{version})")


def update_changelog(root_dir, version):
    changelog_path = root_dir / "CHANGELOG.md"
    if not changelog_path.exists():
        return
    content = changelog_path.read_text("utf-8")
    # Update first header if it starts with [Unreleased] or some version
    content = re.sub(
        r"^## \[([^\]]+)\] - [0-9]{4}-[0-9]{2}-[0-9]{2}",
        f"## [{version}] - {datetime.date.today().isoformat()}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    changelog_path.write_text(content, "utf-8")
    print(f"✅ Updated CHANGELOG.md header (v{version})")


def sync_lockfile():
    try:
        subprocess.run(["uv", "lock"], check=True, capture_output=True)
        print("✅ Synchronized uv.lock")
    except Exception as e:
        print(f"⚠️ Warning: Failed to run 'uv lock': {e}")


def main():
    root_dir = Path(__file__).parent.parent
    pyproject_path = root_dir / "pyproject.toml"

    try:
        version = get_current_version(pyproject_path)
        print(f"🚀 Syncing project version {version}...")

        sync_lockfile()  # Run lock first to have latest client version in lockfile
        client_version = get_client_version(root_dir)

        update_readme(root_dir, version, client_version)
        update_docs(root_dir, version)
        update_website(root_dir, version)
        update_changelog(root_dir, version)

        print("\n✨ Version synchronization complete!")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
