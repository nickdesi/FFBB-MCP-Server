"""
Client FFBB avec gestion automatique du cycle de vie des tokens.

Le singleton FFBBClientFactory gère :
- L'initialisation paresseuse du client FFBB
- Le rafraîchissement proactif des tokens avant expiration
- Le cache SQLite pour les réponses API (TTL 30 min)
"""

import logging
import os
import time
import traceback

from ffbb_api_client_v3 import FFBBAPIClientV3, TokenManager
from ffbb_api_client_v3.utils.cache_manager import CacheConfig, CacheManager

logger = logging.getLogger("ffbb-mcp")

# Durée de vie des tokens en secondes.
# Les tokens FFBB expirent à ~30 min ; on rafraîchit à 25 min par sécurité.
_TOKEN_TTL_SECONDS: int = 25 * 60
_CACHE_TTL_SECONDS: int = 30 * 60


class FFBBClientFactory:
    """Factory singleton pour le client FFBB avec token refresh proactif."""

    _instance: FFBBAPIClientV3 | None = None
    _token_created_at: float = 0.0

    @classmethod
    def _is_token_expired(cls) -> bool:
        """Vérifie si le token actuel est expiré ou sur le point de l'être."""
        if cls._instance is None:
            return True
        elapsed = time.monotonic() - cls._token_created_at
        return elapsed >= _TOKEN_TTL_SECONDS

    @classmethod
    def _create_client(cls) -> FFBBAPIClientV3:
        """Crée une nouvelle instance du client avec des tokens frais."""
        logger.info("Initialisation du client FFBB...")
        cwd = os.getcwd()
        logger.info(f"CWD: {cwd}")

        # On force use_cache=True pour le token manager
        tokens = TokenManager.get_tokens(use_cache=True)

        # Configuration explicite en SQLite avec un TTL de 30 minutes
        cache_config = CacheConfig(
            backend="sqlite", enabled=True, expire_after=_CACHE_TTL_SECONDS
        )
        cache_manager = CacheManager(config=cache_config)

        client = FFBBAPIClientV3.create(
            api_bearer_token=tokens.api_token,
            meilisearch_bearer_token=tokens.meilisearch_token,
            cached_session=cache_manager.session,
            async_cached_session=cache_manager.async_session,
        )
        logger.info("Client FFBB initialisé avec succès (Cache: SQLite).")
        return client

    @classmethod
    def get_client(cls) -> FFBBAPIClientV3:
        """Retourne le client FFBB, en le créant ou rafraîchissant si nécessaire."""
        if cls._is_token_expired():
            if cls._instance is not None:
                logger.info("Token FFBB expiré, rafraîchissement en cours...")
            try:
                cls._instance = cls._create_client()
                cls._token_created_at = time.monotonic()
            except Exception as e:
                logger.error(f"Erreur lors de l'initialisation du client: {e}")
                logger.error(traceback.format_exc())
                raise
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Force la réinitialisation du client (utile pour les tests)."""
        cls._instance = None
        cls._token_created_at = 0.0


def get_client() -> FFBBAPIClientV3:
    """Helper shortcut for FFBBClientFactory.get_client()."""
    return FFBBClientFactory.get_client()
