import asyncio
import logging
import os
import time
import traceback

from ffbb_data_client import FFBBDataClient, TokenManager
from ffbb_data_client.utils.cache_manager import CacheConfig, CacheManager

"""
Client FFBB avec gestion automatique du cycle de vie des tokens.

Le singleton FFBBClientFactory gère :
- L'initialisation paresseuse du client FFBB
- Le rafraîchissement proactif des tokens avant expiration
- Le cache mémoire (30s) pour éviter les doublons réseau concurrents
"""


logger = logging.getLogger("ffbb-mcp")

# Durée de vie des tokens en secondes.
# Les tokens FFBB expirent à ~30 min ; on rafraîchit à 25 min par sécurité.
_TOKEN_TTL_SECONDS: int = 25 * 60
# Cache HTTP court (mémoire) : les données live (poules, calendriers) sont gérées
# par le TTLCache du service layer. Ce cache HTTP évite les doublons d'appel
# réseau strictement concurrents, mais ne doit pas masquer des données stales.
_CACHE_TTL_SECONDS: int = (
    30  # 30 secondes — aligné sur le TTL le plus court du service layer
)


class FFBBClientFactory:
    """Factory singleton pour le client FFBB avec token refresh proactif."""

    _instance: FFBBDataClient | None = None
    _token_created_at: float = 0.0
    # FIX: Lock initialisé à None et créé lazily au premier appel async
    # pour éviter les DeprecationWarning sur Python < 3.10 (Lock lié
    # à la running loop, pas à la loop au moment de la définition de classe).
    _init_lock: asyncio.Lock | None = None
    _refresh_task: asyncio.Task[None] | None = None

    @classmethod
    def _start_background_refresh(cls) -> None:
        """Démarre la tâche de fond pour rafraîchir proactivement le token avant expiration."""
        if cls._refresh_task is not None and not cls._refresh_task.done():
            return
        # Ne pas gaspiller de cycles en mode stdio (1 client = 1 requête à la fois)
        if os.environ.get("MCP_MODE", "stdio").lower() in ("stdio", ""):
            return

        async def _refresher() -> None:
            logger.debug(
                "Tâche de fond de rafraîchissement proactive des tokens démarrée."
            )
            while True:
                try:
                    await asyncio.sleep(60)
                    if cls._instance is not None:
                        elapsed = time.monotonic() - cls._token_created_at
                        # Rafraîchir à 23 minutes (1380s) pour un TTL de 25 minutes (1500s)
                        if elapsed >= 23 * 60:
                            logger.info(
                                "Rafraîchissement proactif du token en tâche de fond..."
                            )
                            if cls._init_lock is None:
                                cls._init_lock = asyncio.Lock()
                            async with cls._init_lock:
                                elapsed_under_lock = (
                                    time.monotonic() - cls._token_created_at
                                )
                                if elapsed_under_lock >= 23 * 60:
                                    cls._instance = await asyncio.to_thread(
                                        cls._create_client
                                    )
                                    cls._token_created_at = time.monotonic()
                                    logger.info(
                                        "Token rafraîchi proactivement avec succès en tâche de fond."
                                    )
                except asyncio.CancelledError:
                    logger.debug("Tâche de fond de rafraîchissement proactive annulée.")
                    break
                except Exception as e:
                    logger.error(
                        "Erreur dans la tâche de fond de rafraîchissement proactive: %s",
                        e,
                    )

        try:
            loop = asyncio.get_running_loop()
            cls._refresh_task = loop.create_task(_refresher())
        except RuntimeError:
            # Pas de loop en cours d'exécution (ex: import global ou environnement de test)
            pass

    @classmethod
    def _is_token_expired(cls) -> bool:
        """Vérifie si le token actuel est expiré ou sur le point de l'être."""
        if cls._instance is None:
            return True
        elapsed = time.monotonic() - cls._token_created_at
        return elapsed >= _TOKEN_TTL_SECONDS

    @classmethod
    def _create_client(cls) -> FFBBDataClient:
        """Crée une nouvelle instance du client avec des tokens frais. Synchrone."""
        logger.debug("Initialisation du client FFBB...")
        # FIX: logger.debug au lieu de logger.info — ce log se déclenche
        # toutes les 25 min en prod lors du refresh de token, c'est du niveau debug.
        logger.debug("CWD: %s", os.getcwd())

        # On force use_cache=True pour le token manager
        tokens = TokenManager.get_tokens(use_cache=True)

        # Configuration dynamique du cache HTTP (Persistance SQLite)
        cache_backend = os.environ.get("FFBB_CACHE_BACKEND", "sqlite")
        cache_expire = int(
            os.environ.get("FFBB_CACHE_EXPIRE_AFTER", str(_CACHE_TTL_SECONDS))
        )

        cache_config = CacheConfig(
            backend=cache_backend,
            enabled=True,
            expire_after=cache_expire,
        )
        cache_manager = CacheManager(config=cache_config)

        client = FFBBDataClient.create(
            api_bearer_token=tokens.api_token,
            meilisearch_bearer_token=tokens.meilisearch_token,
            cached_session=cache_manager.session,
            async_cached_session=cache_manager.async_session,
        )
        logger.info("Client FFBB initialisé avec succès (Cache: mémoire 30s).")
        return client

    @classmethod
    async def get_client_async(cls) -> FFBBDataClient:
        """Retourne le client FFBB en asynchrone, en le créant ou rafraîchissant si nécessaire."""
        cls._start_background_refresh()

        # Première vérification rapide sans lock
        if not cls._is_token_expired():
            return cls._instance  # type: ignore

        # FIX: création lazy du Lock dans la running loop courante
        if cls._init_lock is None:
            cls._init_lock = asyncio.Lock()

        async with cls._init_lock:
            # Deuxième vérification avec le lock (double-check locking)
            if cls._is_token_expired():
                if cls._instance is not None:
                    logger.info("Token FFBB expiré, rafraîchissement en cours...")
                try:
                    # Exécuter la création synchrone dans un thread séparé pour ne pas bloquer l'Event Loop
                    cls._instance = await asyncio.to_thread(cls._create_client)
                    cls._token_created_at = time.monotonic()
                except Exception as e:
                    logger.error(
                        f"Erreur lors de l'initialisation asynchrone du client: {e}"
                    )
                    logger.error(traceback.format_exc())
                    raise
            return cls._instance  # type: ignore

    @classmethod
    def reset(cls) -> None:
        """Force la réinitialisation du client (utile pour les tests)."""
        if cls._refresh_task is not None:
            cls._refresh_task.cancel()
            cls._refresh_task = None
        cls._instance = None
        cls._token_created_at = 0.0
        cls._init_lock = None


async def get_client_async() -> FFBBDataClient:
    """Helper shortcut for FFBBClientFactory.get_client_async()."""
    return await FFBBClientFactory.get_client_async()
