import os
import re

def process_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()
    orig = content
    content = content.replace('dynamique_a.get("serie_actuelle") or {}.get("label") or ""', '(dynamique_a.get("serie_actuelle") or {}).get("label") or ""')
    content = content.replace('dynamique_b.get("serie_actuelle") or {}.get("label") or ""', '(dynamique_b.get("serie_actuelle") or {}).get("label") or ""')
    content = content.replace('eng1.get("id") if isinstance(eng1, dict) else eng1', 'eng1.get("id") if isinstance(eng1, dict) else eng1')

    # Revert specific bad chained expressions if any other exists
    # let's find any `or [].get` or `or {}.get`

    if orig != content:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Patched {filepath}")

def main():
    for root, _, files in os.walk('src/ffbb_mcp'):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                process_file(filepath)

if __name__ == '__main__':
    main()
