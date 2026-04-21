import datetime
import re
import sys
from pathlib import Path


def main():
    root_dir = Path(__file__).parent.parent
    pyproject_path = root_dir / "pyproject.toml"
    index_path = root_dir / "website" / "index.html"
    
    if not pyproject_path.exists() or not index_path.exists():
        print("Missing pyproject.toml or website/index.html")
        sys.exit(1)

    # Extract version
    version_match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject_path.read_text('utf-8'), flags=re.MULTILINE)
    if not version_match:
        print("Version not found in pyproject.toml")
        sys.exit(1)
    version = version_match.group(1)

    # Current dates
    now = datetime.datetime.utcnow()
    iso_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    months_fr = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    nice_date = f"{now.day} {months_fr[now.month]} {now.year}"

    # Read HTML
    content = index_path.read_text('utf-8')

    # Update Version in schema
    content = re.sub(r'("softwareVersion":\s*")[^"]+(")', f'\\g<1>{version}\\g<2>', content)
    # Update dateModified in schema
    content = re.sub(r'("dateModified":\s*")[^"]+(")', f'\\g<1>{iso_date}\\g<2>', content)
    
    # Update Footer date
    # Handle the non-breaking spaces or regular spaces accurately
    content = re.sub(r'(Dernière mise à jour du contenu\s*:\s*)[0-9]+\s+[A-Za-zûé]+\s+[0-9]+', f'\\g<1>{nice_date}', content)

    # Update Hero version badge
    content = re.sub(r'(<div class="badge">V)[^ ]+( Stable</div>)', f'\\g<1>{version}\\g<2>', content)

    # Save
    index_path.write_text(content, 'utf-8')
    print(f"Successfully updated index.html with version {version} and date {nice_date}")

if __name__ == "__main__":
    main()
