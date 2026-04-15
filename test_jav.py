import asyncio

from src.ffbb_mcp.aliases import normalize_query
from src.ffbb_mcp.client import get_client_async


async def main():
    client = await get_client_async()
    print("Normalizing JAV:", normalize_query("JAV"))
    print("Normalizing jav:", normalize_query("jav"))

    res = await client.search_organismes_async("jeanne d'arc vichy")
    print("Search 'jeanne d'arc vichy':", [r.nom for r in res.hits] if res else None)

    res = await client.search_organismes_async("jeanne d'arc de vichy")
    print("Search 'jeanne d'arc de vichy':", [r.nom for r in res.hits] if res else None)

    res = await client.search_organismes_async("vichy")
    print("Search 'vichy':", [r.nom for r in res.hits] if res else None)


asyncio.run(main())
