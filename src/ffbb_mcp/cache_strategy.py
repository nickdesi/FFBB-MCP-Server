from datetime import datetime

# Fenêtres horaires où des matchs peuvent avoir lieu
MATCH_WINDOWS = [
    (2, 13, 20),  # mercredi 13h–20h (U11–U17 jeunes)
    (4, 18, 23),  # vendredi soir 18h–23h (seniors)
    (5, 8, 21),  # samedi 8h–21h
    (6, 8, 21),  # dimanche 8h–21h
]


def is_in_match_window(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    for weekday, h_start, h_end in MATCH_WINDOWS:
        if now.weekday() == weekday and h_start <= now.hour < h_end:
            return True
    return False


def is_post_match_cooling(now: datetime | None = None) -> bool:
    """Lendemain ou soirée après fermeture de fenêtre live."""
    now = now or datetime.now()
    wd, h = now.weekday(), now.hour
    # Dimanche soir après 21h → résultats fraîchement saisis
    if wd == 6 and h >= 21:
        return True
    # Lundi avant 10h → saisies tardives possibles
    if wd == 0 and h < 10:
        return True
    # Mercredi soir après 20h
    if wd == 2 and h >= 20:
        return True
    # Vendredi nuit après 23h
    return bool(wd == 4 and h >= 23)


async def get_poule_ttl(
    poule_id: int,
    get_lives_fn,  # callable async → list[dict]
    now: datetime | None = None,
) -> int:
    now = now or datetime.now()

    # 1. Hors fenêtre horaire → données figées
    if not is_in_match_window(now) and not is_post_match_cooling(now):
        return 86_400  # 24h

    # 2. Période post-match (saisie en retard possible)
    if is_post_match_cooling(now):
        return 1_800  # 30 min

    # 3. Fenêtre live → interroger le signal lives()
    try:
        lives = await get_lives_fn()  # cache 15s, coût quasi nul
        live_poule_ids = {m["poule_id"] for m in lives}
        if poule_id in live_poule_ids:
            return 15  # ⚡ match en cours dans cette poule
        return 300  # fenêtre WE mais cette poule au repos
    except Exception:
        return 300  # fallback si lives() indisponible


# TTLs statiques pour les autres caches
def get_static_ttl(cache_name: str) -> int:
    return {
        "lives": 15,
        "organisme": 86_400,
        "search": 86_400,
        "bilan": 1_800 if is_in_match_window() else 86_400,
        "classement": 1_800 if is_in_match_window() else 86_400,
        "calendrier": 300,
        "poule": 15,
    }.get(cache_name, 3_600)  # fallback 1h
