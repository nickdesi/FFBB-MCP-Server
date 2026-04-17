import time
from ffbb_mcp.services import _normalize_name, _match_team_name

start = time.time()
for _ in range(100000):
    _normalize_name("Jeanne d'Arc de Vichy")
print(f"Time for _normalize_name (cached): {time.time() - start}")

start = time.time()
for i in range(100000):
    _normalize_name(f"Jeanne d'Arc de Vichy {i}")
print(f"Time for _normalize_name (uncached): {time.time() - start}")
