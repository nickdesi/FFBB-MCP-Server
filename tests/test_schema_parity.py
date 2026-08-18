"""Tests de parité et validation de schéma entre FFBB MCP Server et ffbb-data-client.

Ces tests s'assurent que tous les champs, filtres, endpoints Directus et index Meilisearch
utilisés par le serveur MCP existent réellement dans les artefacts de découverte
(discovery) exportés par ffbb-data-client.
"""

from ffbb_data_client.config import (
    MEILISEARCH_INDEX_COMPETITIONS,
    MEILISEARCH_INDEX_ORGANISMES,
    MEILISEARCH_INDEX_PRATIQUES,
    MEILISEARCH_INDEX_RENCONTRES,
    MEILISEARCH_INDEX_SALLES,
    MEILISEARCH_INDEX_TERRAINS,
    MEILISEARCH_INDEX_TOURNOIS,
)
from ffbb_data_client.data import load_discovery_artefact

from ffbb_mcp.services.poule import _SAISONS_FIELDS


class TestSchemaParity:
    """Validation croisée des schémas découverts vs implémentation MCP."""

    def test_saisons_fields_exist_in_openapi_schema(self):
        """Vérifie que tous les champs demandés pour les saisons existent dans le schéma OpenAPI."""
        openapi = load_discovery_artefact("openapi.json")
        schemas = openapi.get("components", {}).get("schemas", {})
        saisons_schema = schemas.get("ItemsFfbbserverSaisons", {})
        assert saisons_schema, (
            "Schéma ItemsFfbbserverSaisons introuvable dans openapi.json"
        )

        valid_props = set(saisons_schema.get("properties", {}).keys())

        # Aucun champ de _SAISONS_FIELDS ne doit être absent du schéma réel (ex: 'nom' ne doit pas y être)
        for field in _SAISONS_FIELDS:
            assert field in valid_props, (
                f"Le champ '{field}' configuré dans _SAISONS_FIELDS n'existe pas dans le schéma Directus ({valid_props})"
            )

    def test_meilisearch_indexes_are_available(self):
        """Vérifie que tous les index Meilisearch interrogés sont marqués comme disponibles."""
        indexes_artefact = load_discovery_artefact("indexes.json")
        available_indexes = set(indexes_artefact.get("available_indexes", []))

        mcp_indexes = [
            MEILISEARCH_INDEX_ORGANISMES,
            MEILISEARCH_INDEX_COMPETITIONS,
            MEILISEARCH_INDEX_RENCONTRES,
            MEILISEARCH_INDEX_SALLES,
            MEILISEARCH_INDEX_PRATIQUES,
            MEILISEARCH_INDEX_TERRAINS,
            MEILISEARCH_INDEX_TOURNOIS,
        ]

        for idx in mcp_indexes:
            assert idx in available_indexes, (
                f"L'index Meilisearch '{idx}' n'est pas disponible dans les artefacts de découverte"
            )

    def test_directus_collections_exist_in_discovery(self):
        """Vérifie que les collections Directus principales existent dans collections.json."""
        collections_artefact = load_discovery_artefact("collections.json")
        known_collections = set(collections_artefact.get("collections", []))

        required_collections = [
            "configuration",
            "ffbbserver_saisons",
            "ffbbserver_organismes",
            "ffbbserver_competitions",
            "ffbbserver_poules",
            "ffbbserver_rencontres",
            "ffbbserver_engagements",
            "ffbbserver_salles",
            "ffbbserver_terrains",
            "ffbbserver_tournois",
        ]

        for col in required_collections:
            assert col in known_collections, (
                f"La collection Directus '{col}' est manquante dans discovery collections.json"
            )
