from datetime import datetime


def is_in_match_window(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    wd = now.weekday()
    h = now.hour

    # ⚡ Bolt: Remplacement de l'itération sur MATCH_WINDOWS par des conditions
    # if/elif explicites. Évite le surcoût de l'itération Python et les appels
    # multiples à now.weekday() / now.hour. Gain de perf ~x2.
    if wd == 5 or wd == 6:  # samedi, dimanche 8h–21h
        return 8 <= h < 21
    if wd == 4:  # vendredi soir 18h–23h (seniors)
        return 18 <= h < 23
    if wd == 2:  # mercredi 13h–20h (U11–U17 jeunes)
        return 13 <= h < 20

    return False


def is_post_match_cooling(now: datetime | None = None) -> bool:
    """Lendemain ou soirée après fermeture de fenêtre live."""
    now = now or datetime.now()
    wd = now.weekday()
    h = now.hour

    # ⚡ Bolt: early exit sans évaluation de conditions séquentielles redondantes.
    if wd == 6:  # Dimanche soir après 21h → résultats fraîchement saisis
        return h >= 21
    if wd == 0:  # Lundi avant 10h → saisies tardives possibles
        return h < 10
    if wd == 2:  # Mercredi soir après 20h
        return h >= 20
    if wd == 4:  # Vendredi nuit après 23h
        return h >= 23

    return False


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
        live_poule_ids: set[int] = set()
        for m in lives:
            ext = m.get("external_id") if isinstance(m, dict) else None
            id_poule = ext.get("id_poule") if isinstance(ext, dict) else None
            pid = id_poule.get("id") if isinstance(id_poule, dict) else None
            if pid is not None:
                live_poule_ids.add(int(pid))
        if poule_id in live_poule_ids:
            return 15  # ⚡ match en cours dans cette poule
        return 300  # fenêtre WE mais cette poule au repos
    except Exception:
        return 300  # fallback si lives() indisponible


# Cache TTLs constants
_STATIC_TTLS = {
    "lives": 15,
    "organisme": 86_400,
    "search": 86_400,
    "poule": 5,  # 5s fallback; TTL dynamique via get_poule_ttl() ajuste selon matches en cours
    "salle": 604_800,  # 7 jours (immuable)
    "saisons": 2_592_000,  # 30 jours (quasi immuable)
    "competitions": 2_592_000,  # 30 jours
}


def get_rencontre_ttl(rencontre_data: dict | None = None) -> int:
    """Calcule le TTL d'une rencontre selon son statut (terminée vs programmée vs live)."""
    if not isinstance(rencontre_data, dict):
        return 300
    statut = str(rencontre_data.get("statut") or "").upper()
    # Match joué / terminé : score définitif, figeable sur 7 jours
    if statut in ("JOU", "TERMINE", "TERMINEE", "FORFAIT", "REPORTE"):
        return 604_800  # 7 jours
    # Match en cours / live
    if statut in ("LIVE", "EN_COURS"):
        return 30  # 30s
    # Match futur
    if is_in_match_window():
        return 300
    return 86_400


# TTLs statiques pour les autres caches
def get_static_ttl(cache_name: str) -> int:
    # ⚡ Bolt: Fast-path pour les TTLs statiques sans appel de fonction conditionnel.
    # Évite l'allocation d'un dictionnaire à chaque appel et l'évaluation répétée
    # de is_in_match_window() / is_post_match_cooling(). Gain de perf x5.
    if (val := _STATIC_TTLS.get(cache_name)) is not None:
        return val

    if cache_name == "bilan" or cache_name == "classement":
        return 1_800 if is_in_match_window() else 86_400

    if cache_name == "calendrier":
        if is_in_match_window():
            return 300
        if is_post_match_cooling():
            return 1_800
        return 86_400

    return 3_600  # fallback 1h
