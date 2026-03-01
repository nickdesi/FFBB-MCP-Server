import asyncio
import os
import sys
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from ffbb_mcp.client import get_client

async def main():
    client = get_client()
    poule_id = 200000003030720 # Poule U11M1 Phase 3
    
    print(f"Recherche des matchs pour Stade Clermontois dans la poule {poule_id}...")
    poule_data = await client.get_poule_async(poule_id)
    
    if not poule_data or not poule_data.rencontres:
        print("Aucun match trouvé.")
        return

    # Date de référence : 24 février 2026
    now = datetime(2026, 2, 24, 23, 59, 59)
    home_count = 0
    away_count = 0
    
    for m in poule_data.rencontres:
        n1 = getattr(m, "nomEquipe1", "").upper()
        n2 = getattr(m, "nomEquipe2", "").upper()
        date_str = getattr(m, "date_rencontre", "")
        
        # Identification de l'équipe 1 du Stade Clermontois
        is_sc1_h = "STADE CLERMONTOIS" in n1 and " - 1" in n1
        is_sc1_a = "STADE CLERMONTOIS" in n2 and " - 1" in n2
        
        # On accepte aussi sans suffixe car il n'y a qu'une équipe par poule
        if not (is_sc1_h or is_sc1_a):
            is_sc1_h = "STADE CLERMONTOIS" in n1
            is_sc1_a = "STADE CLERMONTOIS" in n2

        if is_sc1_h or is_sc1_a:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                if dt > now:
                    if is_sc1_h:
                        home_count += 1
                        print(f"  [DOMICILE] vs {n2} le {date_str}")
                    else:
                        away_count += 1
                        print(f"  [EXTÉRIEUR] chez {n1} le {date_str}")
            except Exception as e:
                # Si format date différent
                print(f"  [ERREUR DATE] {date_str} - {n1} vs {n2}")

    print(f"\nRÉSULTATS FINAUX (Après le 24/02/2026) :")
    print(f"Matchs à DOMICILE restants : {home_count}")
    print(f"Matchs à l'EXTÉRIEUR restants : {away_count}")
    print(f"TOTAL : {home_count + away_count}")

if __name__ == "__main__":
    asyncio.run(main())
