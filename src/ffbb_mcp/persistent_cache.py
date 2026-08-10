"""Cache service persistant (SQLite) — accélère les démarrages à froid.

En mode stdio (recommandé), chaque session MCP démarre dans un *nouveau*
processus : les caches service en mémoire sont donc systématiquement froids.
Ce module persiste les caches service sur disque (SQLite) pour que les
entrées encore valides (dans leur TTL) soient réutilisées d'un redémarrage
à l'autre, sans jamais servir de donnée périmée.

Garanties de fraîcheur :
- Une entrée persistée n'est servie QUE si elle est encore dans son TTL
  d'origine (wall-clock, identique à la durée du cache mémoire actuel).
- `force_refresh=True` purge l'entrée (mémoire + disque) → toujours frais.
- Les TTL appliqués sont EXACTEMENT ceux de la config existante
  (`get_static_ttl` / TTL dynamique des poules). Aucune donnée n'est donc
  plus ancienne qu'avec le cache mémoire seul.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("ffbb-mcp")

_MISS = object()


def _cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = (
        Path(xdg).expanduser() / "ffbb-mcp"
        if xdg
        else Path.home() / ".cache" / "ffbb-mcp"
    )
    return base


def _db_path() -> Path:
    return _cache_dir() / "service_cache.db"


_DB_LOCK = threading.Lock()
_DB_CONN: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _DB_CONN
    if _DB_CONN is None:
        _cache_dir().mkdir(parents=True, exist_ok=True)
        _DB_CONN = sqlite3.connect(str(_db_path()), check_same_thread=False)
        _DB_CONN.execute(
            "CREATE TABLE IF NOT EXISTS service_cache ("
            "name TEXT, key TEXT, value TEXT, expires_at REAL, "
            "PRIMARY KEY(name, key))"
        )
        _DB_CONN.commit()
    return _DB_CONN


class PersistentCache:
    """Enveloppe un cache ``cachetools`` (TTLCache/TLRUCache) avec persistance.

    L'autorité de fraîcheur est ``self._expires`` (wall-clock), indépendante
    du TTL interne (monotone) du cachetools. Une entrée n'est jamais servie
    au-delà de son ``expires_at`` d'origine, même après redémarrage.
    """

    def __init__(self, inner: Any, name: str) -> None:
        self._inner = inner
        self._name = name
        self._ttl_provider: Callable[[Any], float] | None = None
        self._expires: dict[Any, float] = {}
        # Cause du dernier miss (None si hit) : "expired" (TTL dépassé)
        # ou "cold" (clé jamais vue). Consommé par _cache_get pour
        # alimenter ffbb_cache_misses_by_reason_total.
        self._last_miss_reason: str | None = None
        self._load()

    # ------------------------------------------------------------------
    # Persistance (lecture)
    # ------------------------------------------------------------------
    def _load(self) -> None:
        now = time.time()
        try:
            with _DB_LOCK:
                rows = (
                    _get_conn()
                    .execute(
                        "SELECT key, value, expires_at FROM service_cache "
                        "WHERE name=? AND expires_at>?",
                        (self._name, now),
                    )
                    .fetchall()
                )
        except sqlite3.Error as e:  # pragma: no cover - robustness
            logger.warning("Cache persistant (load %s) ignoré: %s", self._name, e)
            return
        for key, value, expires_at in rows:
            try:
                val = json.loads(value)
            except json.JSONDecodeError, TypeError:
                continue
            self._inner[key] = val
            self._expires[key] = expires_at

    def _load_one(self, key: Any, now: float) -> Any | None:
        try:
            with _DB_LOCK:
                row = (
                    _get_conn()
                    .execute(
                        "SELECT value, expires_at FROM service_cache "
                        "WHERE name=? AND key=? AND expires_at>?",
                        (self._name, key, now),
                    )
                    .fetchone()
                )
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            val = json.loads(row[0])
        except json.JSONDecodeError, TypeError:
            return None
        self._inner[key] = val
        self._expires[key] = row[1]
        return val

    # ------------------------------------------------------------------
    # Persistance (écriture)
    # ------------------------------------------------------------------
    def _resolve_ttl(
        self, value: Any, ttl_provider: Callable[[Any], float] | None
    ) -> float:
        if isinstance(value, dict) and "_ttl" in value:
            try:
                return float(value["_ttl"])
            except TypeError, ValueError:
                pass
        if ttl_provider is not None:
            try:
                return float(ttl_provider(value))
            except Exception:
                pass
        return float(getattr(self._inner, "ttl", 300))

    def _persist(self, key: Any, value: Any, ttl: float) -> None:
        expires_at = time.time() + ttl
        try:
            blob = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError, ValueError:
            return
        try:
            with _DB_LOCK:
                _get_conn().execute(
                    "INSERT INTO service_cache(name,key,value,expires_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(name,key) DO UPDATE SET "
                    "value=excluded.value, expires_at=excluded.expires_at",
                    (self._name, key, blob, expires_at),
                )
                _get_conn().commit()
        except sqlite3.Error as e:  # pragma: no cover - robustness
            logger.debug("Cache persistant (write %s) ignoré: %s", self._name, e)

    def _delete_db(self, key: Any) -> None:
        try:
            with _DB_LOCK:
                _get_conn().execute(
                    "DELETE FROM service_cache WHERE name=? AND key=?",
                    (self._name, key),
                )
                _get_conn().commit()
        except sqlite3.Error:
            pass

    # ------------------------------------------------------------------
    # Interface compatible cachetools
    # ------------------------------------------------------------------
    def get(self, key: Any, default: Any = None) -> Any:
        now = time.time()
        exp = self._expires.get(key)
        if exp is not None and now >= exp:
            self._last_miss_reason = "expired"
            self._inner.pop(key, None)
            self._expires.pop(key, None)
            self._delete_db(key)
            return default
        if exp is None:
            val = self._load_one(key, now)
            if val is None:
                self._last_miss_reason = "cold"
                return default
            self._last_miss_reason = None
            return val
        self._last_miss_reason = None
        return self._inner.get(key, default)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._inner[key] = value
        ttl = self._resolve_ttl(value, self._ttl_provider)
        self._expires[key] = time.time() + ttl
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._persist, key, value, ttl)
        except RuntimeError:
            self._persist(key, value, ttl)

    def __getitem__(self, key: Any) -> Any:
        return self._inner[key]

    def __contains__(self, key: Any) -> bool:
        now = time.time()
        exp = self._expires.get(key)
        if exp is not None and now >= exp:
            return False
        return key in self._inner

    def pop(self, key: Any, default: Any = None) -> Any:
        val = self._inner.pop(key, _MISS)
        self._expires.pop(key, None)
        self._delete_db(key)
        return default if val is _MISS else val

    def clear(self) -> None:
        self._inner.clear()
        self._expires.clear()

    def clear_db(self) -> None:
        self._inner.clear()
        self._expires.clear()
        try:
            with _DB_LOCK:
                _get_conn().execute(
                    "DELETE FROM service_cache WHERE name=?", (self._name,)
                )
                _get_conn().commit()
        except sqlite3.Error:
            pass

    @property
    def ttl(self) -> int:
        return int(getattr(self._inner, "ttl", 0))


def make_persistent_cache(
    inner: Any,
    name: str,
    ttl_provider: Callable[[Any], float] | None = None,
) -> Any:
    """Retourne un ``PersistentCache`` (SQLite) sauf opt-out explicite.

    Activé par défaut : les entrées encore dans leur TTL sont réutilisées
    d'un redémarrage à l'autre (accélère les démarrages stdio à froid) sans
    jamais servir de donnée périmée (voir ``PersistentCache``).

    Désactiver avec ``FFBB_SERVICE_CACHE_PERSIST=0`` (ou ``false``/``no``/
    ``off``) pour revenir à un cache purement mémoire.
    """
    if os.environ.get("FFBB_SERVICE_CACHE_PERSIST", "1").lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return inner
    try:
        cache: PersistentCache = PersistentCache(inner, name)
        cache._ttl_provider = ttl_provider
        return cache
    except Exception as e:  # pragma: no cover - robustness
        logger.warning(
            "Cache persistant indisponible (%s), fallback mémoire: %s", name, e
        )
    return inner
