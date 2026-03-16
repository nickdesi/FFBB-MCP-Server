import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_skills_index() -> list[dict[str, Any]]:
    idx_path = _workspace_root() / "external" / "antigravity-awesome-skills" / "skills_index.json"
    with idx_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"\W+", text.lower()) if t]


def score_skill(query: str, skill: dict[str, Any]) -> float:
    q_tokens = set(_tokenize(query))
    text = " ".join([skill.get("name", ""), skill.get("description", ""), skill.get("category", "")])
    s_tokens = set(_tokenize(text))
    overlap = len(q_tokens & s_tokens)

    # fuzzy similarity on combined text
    ratio = SequenceMatcher(None, query.lower(), text.lower()).ratio()

    return overlap + ratio * 3.0


def find_skills(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    skills = load_skills_index()
    scored = []
    for s in skills:
        sc = score_skill(query, s)
        if sc > 0:
            scored.append((sc, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_k]]


def preview_skill(skill: dict[str, Any], max_lines: int = 200) -> str:
    skill_path = _workspace_root() / "external" / "antigravity-awesome-skills" / skill.get("path", "")
    # prefer README.md or README
    for name in ("README.md", "README", "readme.md"):
        p = skill_path / name
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip().splitlines()[:max_lines]
            except Exception:
                return [f"Could not read {p}"]
    return [f"No README found in {skill_path}"]


def cli():
    import argparse

    p = argparse.ArgumentParser("skill-router")
    p.add_argument("query", nargs="+", help="User request to route to skills")
    p.add_argument("--top", type=int, default=5)
    args = p.parse_args()
    query = " ".join(args.query)
    results = find_skills(query, top_k=args.top)
    if not results:
        print("No matching skills found.")
        return
    for i, r in enumerate(results, 1):
        print(f"[{i}] id: {r.get('id')}  category: {r.get('category')}\n    desc: {r.get('description')[:200]}\n    path: {r.get('path')}\n")
    # preview first skill README
    print("---\nPreview of first skill README (if available):\n")
    preview_lines = preview_skill(results[0], max_lines=50)
    if isinstance(preview_lines, list):
        for ln in preview_lines:
            print(ln)
    else:
        print(preview_lines)


if __name__ == "__main__":
    cli()
