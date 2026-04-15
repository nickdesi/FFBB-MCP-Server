import asyncio

from src.ffbb_mcp.client import get_client_async
from src.ffbb_mcp.services import ffbb_bilan_service


async def main():
    print("Testing JAV U11M1 bilan")

    client = await get_client_async()
    res = await client.search_organismes_async("jeanne d'arc de vichy")
    jav_club = res.hits[0]
    org_id = jav_club.id
    print(f"JAV org ID: {org_id}")

    try:
        bilan = await ffbb_bilan_service(club_name="jav", categorie="U11M")
        print("Bilan result:", bilan)
    except Exception as e:
        print("Error getting bilan:", e)


asyncio.run(main())
