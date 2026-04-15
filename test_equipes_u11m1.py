import asyncio

from src.ffbb_mcp.services import ffbb_equipes_club_service


async def main():
    equipes = await ffbb_equipes_club_service(organisme_id=9220, filtre="U11M1")
    print(equipes)


asyncio.run(main())
