import asyncio

from src.ffbb_mcp.services import ffbb_get_classement_service


async def main():
    print("Testing JAV U11M1 classement")
    try:
        # Phase 3 poule id for U11M1 JAV
        res = await ffbb_get_classement_service(
            poule_id=200000003030720, target_organisme_id=9220, target_num=1
        )
        for c in res:
            if c.get("is_target"):
                print("Target team:", c)
    except Exception as e:
        print("Error getting classement:", e)


asyncio.run(main())
