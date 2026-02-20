import logging
import os
import traceback

from ffbb_api_client_v3 import FFBBAPIClientV3, TokenManager
from ffbb_api_client_v3.utils.cache_manager import CacheConfig, CacheManager

logger = logging.getLogger("ffbb-mcp")


class FFBBClientFactory:
    _instance: FFBBAPIClientV3 | None = None

    @classmethod
    def get_client(cls) -> FFBBAPIClientV3:
        """Retourne le client FFBB, en le créant si nécessaire."""
        if cls._instance is None:
            try:
                logger.info("Initialisation du client FFBB...")
                cwd = os.getcwd()
                logger.info(f"CWD: {cwd}")

                # On force use_cache=True pour le token manager
                tokens = TokenManager.get_tokens(use_cache=True)

                # Configuration explicite en SQLite avec un TTL de 30 minutes
                cache_config = CacheConfig(
                    backend="sqlite", enabled=True, expire_after=1800
                )
                cache_manager = CacheManager(config=cache_config)

                cls._instance = FFBBAPIClientV3.create(
                    api_bearer_token=tokens.api_token,
                    meilisearch_bearer_token=tokens.meilisearch_token,
                    cached_session=cache_manager.session,
                    async_cached_session=cache_manager.async_session,
                )
                logger.info("Client FFBB initialisé avec succès (Cache: SQLite).")
            except Exception as e:
                logger.error(f"Erreur lors de l'initialisation du client: {e}")
                logger.error(traceback.format_exc())
                raise e
        return cls._instance


def get_client() -> FFBBAPIClientV3:
    """Helper shortcut for FFBBClientFactory.get_client()."""
    return FFBBClientFactory.get_client()
