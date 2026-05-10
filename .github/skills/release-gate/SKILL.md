---
name: release-gate
description: "Use when: user asks to push, tag, release, publish, create a version, validate synchronization, fix CI, inspect GitHub Actions, or make changes safe for GitHub. Runs the FFBB MCP Server release-readiness workflow, adapted from sickn33 skills lint-and-validate, verification-before-completion, git-pushing, iterate-pr, and codebase-audit-pre-push."
argument-hint: "push|tag|release|publish|ci"
user-invocable: true
---

# Release Gate — FFBB MCP Server

Use this skill for any request involving `push`, `tag`, `release`, `publish`, `version`, CI, GitHub Actions, or remote synchronization.

This workflow adapts the relevant patterns from `sickn33/antigravity-awesome-skills`:
- `lint-and-validate`: validate after changes.
- `verification-before-completion`: evidence before success claims.
- `git-pushing`: commit and push only when explicitly requested.
- `iterate-pr`: follow GitHub checks until green.
- `codebase-audit-pre-push`: inspect diffs and side effects before pushing.

## Non-negotiable rules

- Use `rtk` for all terminal commands.
- Work from the repository root.
- Do not claim completion without fresh command output.
- Do not push, tag, release, or publish if any local gate fails.
- Keep changes surgical; do not refactor unrelated code.
- Inspect and revert unintended runtime/test mutations, especially `src/ffbb_mcp/acronyms_cache.json`.

## Required local gate before push/tag/release

Run the full gate, in this order:

1. Version alignment:
   - `rtk uv run python tools/check_version_alignment.py`
2. Formatting:
   - `rtk uv run ruff format --check .`
3. Linting:
   - `rtk uv run ruff check .`
4. Types:
   - `rtk uv run mypy src`
5. Tests:
   - `rtk uv run pytest`
6. Repository inspection:
   - `rtk git status --short --branch`
   - `rtk git diff --stat`
   - targeted `rtk git diff -- ./path` for changed files.

If version files changed, run `rtk uv run python tools/sync_version.py`, inspect the diff, then rerun the required local gate.

## Push workflow

Only when the user explicitly asks to push or publish changes:

1. Run the required local gate.
2. Inspect staged and unstaged changes.
3. Revert unrelated changes and generated side effects not intentionally part of the task.
4. Commit with a conventional commit message.
5. Push the branch.
6. Inspect GitHub Actions after pushing:
   - `rtk gh run list --limit 5`
   - For failures, inspect only failed logs with `rtk gh run view <run-id> --log-failed`.
7. If CI fails, fix the root cause locally, rerun the relevant gate plus any affected tests, commit, push, and re-check CI.

## Tag / release workflow

For a new tag or release:

1. Confirm the intended version and that the tag does not already exist.
2. Update `pyproject.toml` and run `rtk uv run python tools/sync_version.py`.
3. Inspect synchronized files, especially:
   - `README.md`
   - `CHANGELOG.md`
   - `docs/TOOLS_REFERENCE.md`
   - `website/index.html`
   - `website/sitemap.xml`
   - `website-docs/reference/tools.md`
   - `uv.lock`
4. Run the required local gate.
5. Commit release changes.
6. Create an annotated tag.
7. Push branch and tag.
8. Inspect GitHub Actions until all relevant runs succeed.

## CI-fix workflow

When GitHub Actions fail:

1. Read the failed job logs before changing code.
2. Identify the root cause, not just the check name.
3. Make minimal fixes.
4. Run the exact local check matching the failure, then the required gate if pushing.
5. Push only after local evidence is clean.
6. Follow CI until green, or report the blocker with the failing check and evidence.

## Completion report

Final response must include only:
- Changed files.
- Validation commands that passed.
- Push/tag/CI status if applicable.
- Any remaining blocker or explicit risk.
