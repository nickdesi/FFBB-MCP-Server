import sys
import asyncio
import json
from pathlib import Path

# Add src to python path so we can import our service
sys.path.insert(0, str(Path('./src').resolve()))

from ffbb_mcp.services import search_rencontres_service

async def main():
    try:
        res = await search_rencontres_service("issoire")
        print(json.dumps(res[:2], default=str, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
