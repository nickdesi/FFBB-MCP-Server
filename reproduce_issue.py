import logging

# Configure root logger
logging.basicConfig(level=logging.DEBUG)

# Explicitly set level for library loggers if needed
logging.getLogger("ffbb_api_client_v2").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)  # Catch HTTP requests

import os
import sys

# Add src to path
sys.path.insert(0, os.path.abspath("src"))

from ffbb_api_client_v2 import TokenManager

from ffbb_mcp.server import get_client

try:
    print(f"CWD: {os.getcwd()}")
    print("Attempting to get client...")

    import requests

    print("Fetching configuration directly...")
    resp = requests.get(
        "https://api.ffbb.app/items/configuration",
        headers={"User-Agent": "okhttp/4.12.0"},
    )
    print(f"Config Response Status: {resp.status_code}")
    try:
        data = resp.json()
        print(f"Config Data: {data}")
    except:
        print(f"Config Body: {resp.text}")

    # Inspect tokens
    tokens = TokenManager.get_tokens(use_cache=False)
    print(f"FULL API Token: {tokens.api_token}")
    print(f"FULL Meilisearch Token: {tokens.meilisearch_token}")

    client = get_client()
    print("Client initialized successfully.")

    print("Testing get_saisons()...")
    saisons = client.get_saisons()
    print(f"Found {len(saisons)} saisons.")
    if saisons:
        print(f"First saison: {saisons[0]}")

    print("Searching for 'Stade Clermontois'...")
    res = client.search_organismes("Stade Clermontois")
    if res and res.hits:
        print(f"Found {len(res.hits)} results.")
        first_hit = res.hits[0]
        print(f"First result: {first_hit.nom} (ID: {first_hit.id})")

        print(f"Attempting get_organisme({first_hit.id})...")
        try:
            org = client.get_organisme(first_hit.id)
            print(f"Organisme details: {org}")
        except Exception as e:
            print(f"get_organisme failed: {e}")

            # Try to debug with requests and headers
            print("Debugging with requests...")
            url = f"https://api.ffbb.app/items/ffbbserver_organismes/{first_hit.id}"
            headers = {
                "User-Agent": "okhttp/4.12.0",
                "Authorization": f"Bearer {tokens.api_token}",
                "Origin": "capacitor://localhost",  # Test typical mobile app origin
            }
            resp = requests.get(url, headers=headers)
            print(f"Manual Request Status: {resp.status_code}")
            print(f"Manual Request Response: {resp.text[:200]}...")

            # Try without Origin
            headers.pop("Origin")
            resp = requests.get(url, headers=headers)
            print(f"Manual Request (No Origin) Status: {resp.status_code}")

            # Try with web user agent
            headers["User-Agent"] = (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            resp = requests.get(url, headers=headers)
            print(f"Manual Request (Web UA) Status: {resp.status_code}")

    else:
        print("No results found for Stade Clermontois.")
except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
