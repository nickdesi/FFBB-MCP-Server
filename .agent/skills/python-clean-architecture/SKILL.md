---
name: python-clean-architecture
description: Python Clean Architecture & MCP Server Best Practices
---

# Python Clean Architecture & FastMCP - Lessons Learned

When building or refactoring Python applications, particularly FastMCP servers, strict adherence to these rules prevents cyclic errors, linting failures, and architectural drift.

## 1. Exception Handling & Chaining (Ruff B904)

**Never sink exceptions without chaining them.**
❌ **BAD:**

```python
try:
    result = await do_something()
except Exception as e:
    raise McpError(f"Failed: {e}")
```

✅ **GOOD:**

```python
try:
    result = await do_something()
except Exception as e:
    raise McpError(f"Failed: {e}") from e
```

## 2. FastMCP Tool Signatures & Pydantic

FastMCP maps tools based on function names. When refactoring tools and separating them into different modules:

- Ensure the registered tool name (e.g. `ffbb_calendrier_club`) exactly matches the expected tool list across tests.
- When decoupling schemas, ensure input arguments cleanly accept Pydantic models.
- **Never rename a tool** without verifying all related `mcp.tool()` decorators and test assertions (like `test_server_tools_importable`).

## 3. External API Mocks

When testing service logic that wraps an external library (like `FFBBApiClientV3`):

- Do not make the service apply filters that the API is supposed to handle natively.
- Example: If `client.get_saisons(active_only=True)` exists, the mock in tests must intercept `active_only=True` rather than the service filtering it afterwards. Mock behavior must faithfully reflect the external SDK's responsibilities.

## 4. Asynchronous Singletons

When implementing a cached or singleton client (like `client.py`):

- Do not perform synchronous HTTP or CPU blocking operations inside an `async def`.
- Instead of raw instantiation, use `await asyncio.to_thread(cls._create_client)` to keep the event loop free in ASGI servers.
- Always use `asyncio.Lock()` to prevent race conditions during refresh tokens rather than raw synchronous logic.

## 5. File Architecture & Imports

A clean architecture means:

- `schemas.py`: Pure Pydantic models only. No business logic.
- `services.py`: Pure business functions handling external APIs and error normalization.
- `server.py`: Pure FastMCP routing. Only depends on `schemas` and `services`. Never imports external proprietary sdks directly if the service layer is designed for it.
- **Check imports carefully!** (Lint rule F401). Unused imports slip in quickly during large refactoring. Always run `ruff check` right after mass edits.

## 6. API Filtering Logic (Real-world Data Subtleties)

- **Do not trust string exact match limits:** In FFBB, searching for "Stade Clermontois U11M1" directly in a `rencontres` endpoint fails.
- You MUST decouple semantic intent into chained API calls:
  1. Find Club ID.
  2. Find Club Teams (filter locally based on age category "U11" and sex "M").
  3. Query matches of specific `poule_id` for that team.
- Agent Prompts (`prompts.py`) must document this explicitly for LLMs.

Always run `uv run pytest tests/` and `uv run ruff check src tests` progressively, step by step, rather than 20 files at once.
