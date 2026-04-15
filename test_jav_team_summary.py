import asyncio

from src.ffbb_mcp.services import ffbb_saison_bilan_service


async def main():
    print("Testing JAV U11M1 saison_bilan_service")
    try:
        bilan = await ffbb_saison_bilan_service(
            organisme_id=9220, categorie="U11M", numero_equipe=1
        )
        print("Bilan result:", bilan)
    except Exception as e:
        print("Error getting bilan:", e)


asyncio.run(main())
