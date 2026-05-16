"""Gestion des alias et acronymes de clubs FFBB.

Ce module fournit :
- Un dictionnaire statique d'alias bien connus (CLUB_ALIASES)
- Un cache persistant d'acronymes auto-enrichi (acronyms_cache.json)
- normalize_query() : résolution d'alias dans les recherches
- resolve_acronym() : résolution spécifique d'acronymes (< 7 chars, tout en majuscules)
- enrich_acronym_cache() : enrichissement automatique après chaque recherche réussie
"""

import json
import logging
import os
import re
from pathlib import Path
from threading import Lock

logger = logging.getLogger("ffbb-mcp")

# ---------------------------------------------------------------------------
# Dictionnaire statique d'alias (toujours en lowercase)
# ---------------------------------------------------------------------------

CLUB_ALIASES = {
    "jav": "jeanne d'arc de vichy",
    "ja vichy": "jeanne d'arc de vichy",
    "scba": "stade clermontois basket auvergne",
    "scbf": "stade clermontois basket feminin",
    "asvel": "lyon villeurbanne",
    "ldlc asvel": "lyon villeurbanne",
    "chorale": "roanne",
    "cb": "cholet basket",
    "jlb": "jl bourg",
    "bourg": "jl bourg",
    "bcm": "gravelines dunkerque",
    "gravelines": "bcm gravelines dunkerque",
    "pau": "elan bearnais",
    "msb": "le mans sarthe basket",
    "le mans": "le mans sarthe basket",
    "sluc": "nancy",
    "nancy": "sluc nancy",
    "sig": "strasbourg",
    "csp": "limoges csp",
    "essm": "essm le portel",
    "sqbb": "saint quentin basket ball",
    "ada": "ada blois basket 41",
    "alm": "alm evreux basket",
    "stb": "saint thomas basket le havre",
    "rmb": "rouen metropole basket",
    "amsb": "aix maurienne savoie basket",
    "ujap": "ujap quimper",
    "urb": "union rennes basket 35",
    "cep": "cep lorient basket",
    "olb": "orleans loiret basket",
    "esbva": "esb villeneuve d'ascq lille metropole",
    "blma": "basket lattes montpellier",
    "bbd": "boulazac basket dordogne",
    "htv": "hyeres toulon var basket",
    "tgb": "tarbes gespe bigorre",
    "asa": "alliance sport alsace",
    "asm": "as monaco basket",
    "jsf": "jsf nanterre",
    "lmb": "lille metropole basket",
    "lyonso": "lyonso basket",
    "avbb": "aurore vitre basket bretagne",
    "rac": "rac basket premiere",
    "svbd": "saint-vallier basket drôme",
    "mba": "mulhouse basket agglomeration",
    "besac": "besancon avenir comtois",
    "cbc": "caen basket calvados",
    "utlpb": "union tarbes lourdes pyrenees basket",
    "eab": "etoile angers basket",
    "bco": "sasp bc orchies",
    "fpb": "sas fos provence basket",
    "usom": "uso mondeville basket",
    "cnb": "cavigal nice basket 06",
    "lbb": "landerneau bretagne basket",
    "cbbs": "charnay basket bourgogne sud",
    "fcba": "flammes carolo basket ardennes",
    "sahb": "saint-amand hainaut basket",
}

# ---------------------------------------------------------------------------
# Expressions régulières pré-compilées (Optimisation des performances)
# ---------------------------------------------------------------------------
# Le pré-calcul des regex évite le surcoût de la compilation dynamique lors
# de l'exécution (notamment dans la boucle de `normalize_query`),
# ce qui offre un gain de performance notable (~x3 sur la normalisation).

_COMPILED_ALIASES = [
    (alias, re.compile(r"\b" + re.escape(alias) + r"\b"), official)
    for alias, official in CLUB_ALIASES.items()
    if not re.search(r"\b" + re.escape(alias) + r"\b", official)
]

# ---------------------------------------------------------------------------
# Cache persistant d'acronymes (acronyms_cache.json)
# ---------------------------------------------------------------------------

_DEFAULT_ACRONYMS = {
    "ASVEL": "Villeurbanne",
    "JAV": "Jeanne d'Arc de Vichy",
    "SLUC": "Nancy",
    "SCBA": "Stade Clermontois",
    "JDA": "Dijon",
    "BCM": "Gravelines",
    "SIG": "Strasbourg",
    "MSB": "Le Mans",
    "GB": "GERZAT BASKET",
    "SCBF": "STADE CLERMONTOIS BASKET FEMININ",
    "CSP": "LIMOGES CSP",
    "ESSM": "ESSM LE PORTEL",
    "SQBB": "SAINT QUENTIN BASKET BALL",
    "ADA": "ADA BLOIS BASKET 41",
    "ALM": "ALM EVREUX BASKET",
    "STB": "SAINT THOMAS BASKET LE HAVRE",
    "RMB": "ROUEN METROPOLE BASKET",
    "AMSB": "AIX MAURIENNE SAVOIE BASKET",
    "UJAP": "UJAP QUIMPER",
    "URB": "UNION RENNES BASKET 35",
    "CEP": "CEP LORIENT BASKET",
    "OLB": "ORLEANS LOIRET BASKET",
    "ESBVA": "ESB VILLENEUVE D'ASCQ LILLE METROPOLE",
    "BLMA": "BASKET LATTES MONTPELLIER",
    "BBD": "BOULAZAC BASKET DORDOGNE",
    "HTV": "HYERES TOULON VAR BASKET",
    "TGB": "TARBES GESPE BIGORRE",
    "ASA": "ALLIANCE SPORT ALSACE",
    "ASM": "AS MONACO BASKET",
    "JSF": "JSF NANTERRE",
    "LMB": "LILLE METROPOLE BASKET",
    "LYONSO": "LYONSO BASKET",
    "AVBB": "AURORE VITRE BASKET BRETAGNE",
    "RAC": "RAC BASKET PREMIERE",
    "SVBD": "SAINT-VALLIER BASKET DRÔME",
    "MBA": "MULHOUSE BASKET AGGLOMERATION",
    "BESAC": "BESANCON AVENIR COMTOIS",
    "CBC": "CAEN BASKET CALVADOS",
    "UTLPB": "UNION TARBES LOURDES PYRENEES BASKET",
    "EAB": "ETOILE ANGERS BASKET",
    "BCO": "SASP BC ORCHIES",
    "FPB": "SAS FOS PROVENCE BASKET",
    "USOM": "USO MONDEVILLE BASKET",
    "CNB": "CAVIGAL NICE BASKET 06",
    "LBB": "LANDERNEAU BRETAGNE BASKET",
    "CBBS": "CHARNAY BASKET BOURGOGNE SUD",
    "FCBA": "FLAMMES CAROLO BASKET ARDENNES",
    "SAHB": "SAINT-AMAND HAINAUT BASKET",
}


def _resolve_cache_dir() -> Path:
    """Retourne un dossier cache utilisateur robuste et écrivable."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg).expanduser() / "ffbb-mcp"
    return Path.home() / ".cache" / "ffbb-mcp"


_CACHE_DIR = _resolve_cache_dir()
_CACHE_FILE = _CACHE_DIR / "acronyms_cache.json"
_cache_lock = Lock()
_acronyms_cache: dict[str, str] | None = None
_acronyms_cache_upper: dict[str, str] | None = None


def _load_acronyms_cache() -> dict[str, str]:
    """Charge le cache d'acronymes depuis le fichier JSON.

    Si le fichier n'existe pas, l'initialise avec les valeurs par défaut.
    """
    global _acronyms_cache
    global _acronyms_cache_upper
    if _acronyms_cache is not None:
        return _acronyms_cache

    with _cache_lock:
        # Double-check après acquisition du lock
        if _acronyms_cache is not None:
            return _acronyms_cache

        if _CACHE_FILE.exists():
            try:
                data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _acronyms_cache_upper = {k.upper(): v for k, v in data.items()}
                    _acronyms_cache = data
                    logger.info(
                        "Cache d'acronymes chargé: %d entrées depuis %s",
                        len(data),
                        _CACHE_FILE,
                    )
                    return _acronyms_cache
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Erreur lecture %s: %s — réinitialisation", _CACHE_FILE, e
                )

        # Initialisation avec les valeurs par défaut
        _acronyms_cache_upper = {k.upper(): v for k, v in _DEFAULT_ACRONYMS.items()}
        _acronyms_cache = dict(_DEFAULT_ACRONYMS)
        _save_acronyms_cache()
        logger.info(
            "Cache d'acronymes initialisé avec %d entrées par défaut",
            len(_acronyms_cache),
        )
        return _acronyms_cache


def _save_acronyms_cache() -> None:
    """Sauvegarde le cache d'acronymes dans le fichier JSON."""
    if _acronyms_cache is None:
        return
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps(_acronyms_cache, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Erreur sauvegarde %s: %s", _CACHE_FILE, e)


_SKIP_WORDS: frozenset[str] = frozenset(
    {"de", "du", "le", "la", "les", "et", "en", "des", "aux"}
)


def _extract_initials(name: str) -> str:
    """Extrait les initiales d'un nom officiel FFBB.

    Prend la première lettre de chaque mot commençant par une majuscule.
    Ignore les mots courants courts (de, du, le, la, les, d', l', et).
    """
    words = name.split()
    initials = []
    for w in words:
        # ⚡ Bolt: Accès direct par index plutôt que de créer un tuple et
        # d'appeler startswith, évitant des allocations inutiles.
        # Supprimer les articles collés (d', l', D', L')
        if len(w) >= 2 and w[1] == "'" and w[0] in ("d", "l", "D", "L"):
            clean = w[2:]
        else:
            clean = w

        if not clean:
            continue
        if clean.lower() in _SKIP_WORDS:
            continue
        if clean[0].isupper():
            initials.append(clean[0])
    return "".join(initials)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


def resolve_acronym(query: str) -> str:
    """Résout un acronyme de club vers son nom complet.

    Règle de détection : si le terme est entièrement en majuscules
    et fait moins de 7 caractères, tenter une résolution via le cache.

    Retourne le nom résolu si trouvé, sinon retourne `query` tel quel.
    """
    if not query or len(query) >= 7:
        return query

    stripped = query.strip()
    if not stripped:
        return query

    # Vérifier que c'est bien un acronyme (tout en majuscules, lettres uniquement)
    if not stripped.isalpha() or not stripped.isupper():
        return query

    _load_acronyms_cache()

    # Recherche case-insensitive dans le cache
    assert _acronyms_cache_upper is not None
    if value := _acronyms_cache_upper.get(stripped.upper()):
        logger.info("Acronyme résolu: %s → %s", stripped, value)
        return value

    return query


def enrich_acronym_cache(official_name: str) -> None:
    """Enrichit automatiquement le cache d'acronymes après une recherche réussie.

    Extrait les initiales du nom officiel retourné par la FFBB.
    Si ces initiales ne sont pas déjà dans le cache, les ajoute
    avec le nom complet comme valeur et sauvegarde immédiatement.
    """
    if not official_name or len(official_name) < 3:
        return

    initials = _extract_initials(official_name)
    if not initials or len(initials) < 2 or len(initials) >= 7:
        return

    cache = _load_acronyms_cache()

    # Vérifier si l'acronyme existe déjà (case-insensitive)
    # _load_acronyms_cache guarantees _acronyms_cache_upper is initialized
    initials_upper = initials.upper()
    assert _acronyms_cache_upper is not None
    if initials_upper in _acronyms_cache_upper:
        return

    with _cache_lock:
        cache[initials] = official_name
        _acronyms_cache_upper[initials_upper] = official_name
        _save_acronyms_cache()
        logger.info("Acronyme auto-enrichi: %s → %s", initials, official_name)


_APOSTROPHES_MAP = str.maketrans("\u2019\u2018\u201b\u0060", "''''")


def _normalize_apostrophes(text: str) -> str:
    """Normalise toutes les variantes typographiques d'apostrophe en apostrophe ASCII.

    Variantes couvertes : \u2019 (U+2019), \u2018 (U+2018), \u201b (U+201B), \u0060 (backtick).
    """
    # Fast-path : la plupart des textes sont déjà ASCII et ne contiennent pas de backtick.
    if text.isascii() and "`" not in text:
        return text

    return text.translate(_APOSTROPHES_MAP)


def normalize_query(query: str) -> str:
    """Normalize a search query to replace common club abbreviations
    or alternative names with their official FFBB names.
    This helps the FFBB API find the correct results.

    Applique aussi la résolution d'acronymes en premier.
    """
    if not query:
        return query

    # 0. Normalisation des apostrophes typographiques → apostrophe ASCII
    query = _normalize_apostrophes(query)

    # 1. Résolution d'acronyme en priorité
    resolved = resolve_acronym(query)
    if resolved != query:
        return resolved

    # 2. Normalisation via le dictionnaire statique
    normalized = query.lower().strip()

    # Try exact match first
    if normalized in CLUB_ALIASES:
        return CLUB_ALIASES[normalized]

    # Replace whole words
    # Fast path substring check before regex sub avoids expensive engine invocation
    for alias, alias_pattern, official in _COMPILED_ALIASES:
        if alias in normalized:
            normalized = alias_pattern.sub(official, normalized)

    # Remove excessive spaces
    normalized = " ".join(normalized.split())
    return normalized
