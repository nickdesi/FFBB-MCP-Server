import asyncio

from src.ffbb_mcp.services import ffbb_bilan_service


async def main():
    print("Testing JAV U11M2 bilan")
    try:
        bilan = await ffbb_bilan_service(club_name="jav", categorie="U11M2")
        print("Bilan result:", bilan)
    except Exception as e:
        print("Error getting bilan:", e)


asyncio.run(main())
