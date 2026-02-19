import logging
import os
import traceback

from ffbb_api_client_v2 import FFBBAPIClientV2, TokenManager
from ffbb_api_client_v2.utils.cache_manager import CacheConfig, CacheManager

logger = logging.getLogger("ffbb-mcp")


class FFBBClientFactory:
    _instance: FFBBAPIClientV2 | None = None

    @classmethod
    def get_client(cls) -> FFBBAPIClientV2:
        """Retourne le client FFBB, en le créant si nécessaire."""
        if cls._instance is None:
            try:
                logger.info("Initialisation du client FFBB...")
                cwd = os.getcwd()
                logger.info(f"CWD: {cwd}")

                # Configuration explicite en mémoire
                cache_config = CacheConfig(
                    backend="memory", enabled=False, expire_after=3600
                )
                cache_manager = CacheManager(config=cache_config)

                # On force use_cache=False pour le token manager
                tokens = TokenManager.get_tokens(use_cache=False)

                cls._instance = FFBBAPIClientV2.create(
                    api_bearer_token=tokens.api_token,
                    meilisearch_bearer_token=tokens.meilisearch_token,
                    cached_session=cache_manager.session,
                )
                logger.info("Client FFBB initialisé avec succès (Cache: Memory).")
            except Exception as e:
                logger.error(f"Erreur lors de l'initialisation du client: {e}")
                logger.error(traceback.format_exc())
                raise e
        return cls._instance


def get_client() -> FFBBAPIClientV2:
    """Helper shortcut for FFBBClientFactory.get_client()."""
    return FFBBClientFactory.get_client()
