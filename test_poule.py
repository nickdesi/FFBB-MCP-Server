import sys
import asyncio
import json
from pathlib import Path

# Add src to python path so we can import our service
sys.path.insert(0, str(Path('./src').resolve()))

from ffbb_mcp.services import get_poule_service

async def main():
    try:
        res = await get_poule_service("200000003035105")
        
        matches = []
        for m in res.get("rencontres", []):
            if 'issoire' in str(m.get('nomEquipe1', '')).lower() or 'issoire' in str(m.get('nomEquipe2', '')).lower():
                matches.append(m)
        print(json.dumps(matches, default=str, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
