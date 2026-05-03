# FFBB MCP Server — Copilot Instructions

## Project
Python MCP (Model Context Protocol) server exposing French basketball federation (FFBB) data.
Built with `mcp[cli]`, `uvicorn`, `starlette`, `cachetools`, `ffbb-data-client`.

## Stack
- **Package manager**: `uv` (lockfile: `uv.lock`). Never use `pip install` directly.
- **Formatter/Linter**: `ruff format` + `ruff check`. Never use `black`.
- **Type checker**: `mypy`
- **Test runner**: `pytest` with `pytest-asyncio`
- **Runtime**: Python 3.10+

## Key commands
```bash
uv sync --extra dev        # Install all dependencies
uv run ruff format .       # Format code
uv run ruff check --fix .  # Lint + autofix
uv run mypy src            # Type check
uv run pytest              # Run tests
```

## Conventions
- All source code lives in `src/ffbb_mcp/`
- Services are in `src/ffbb_mcp/services.py` (single file, not a package)
- Cache strategy in `src/ffbb_mcp/cache_strategy.py`
- Prompts/guardrails in `src/ffbb_mcp/prompts.py`
- Tests in `tests/`
- One-off tooling scripts in `tools/`

## CI
- CI uses `ruff format --check` (not black). Don't introduce black.
- Formatting violations will fail CI. Always run `uv run ruff format .` before committing.
- Pre-commit hook (`.pre-commit-config.yaml`) handles this automatically if installed.

## Do not
- Commit directly to `main` without running tests
- Add dependencies without updating `uv.lock` (`uv add <pkg>`)
- Use `pip`, `poetry`, or `black`
