Skill Router

Usage:

- Run a quick search from workspace root:

```bash
python tools/skill_router/router.py "help me design an API" --top 5
```

This script loads `external/antigravity-awesome-skills/skills_index.json`, ranks skills by simple token overlap + fuzzy match, and prints top matches with a README preview for the top candidate.

Next steps:
- Improve ranking with TF-IDF or embedding search.
- Add safe-filtering by `risk` field before invoking skills.
- Provide a programmatic API for integration with other tooling.
