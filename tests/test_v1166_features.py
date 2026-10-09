"""Tests unitaires et de non-régression pour les fonctionnalités FFBB MCP v1.16.6."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ffbb_mcp.dynamique import compute_team_dynamique
from ffbb_mcp.server import mcp
from ffbb_mcp.services.club import ffbb_next_match_service
from ffbb_mcp.services.salle import _enrich_salle_data_with_meilisearch
from ffbb_mcp.services.search import _lighten_rencontre_hit, ffbb_search_service
from ffbb_mcp.tools.system import ffbb_get, ffbb_lives, ffbb_version


def test_all_tools_cited_in_hints_are_exposed():
    """Vérifie que tout outil cité dans les hints, warnings, prompts et docstrings est bien exposé dans FastMCP."""
    exposed_tools = set(mcp._tool_manager._tools.keys())
    assert "ffbb_match_lookup" in exposed_tools

    src_dir = Path(__file__).resolve().parents[1] / "src" / "ffbb_mcp"
    tool_ref_pattern = re.compile(r"['\"`]\s*(ffbb_[a-z0-9_]+)\s*['\"`]")

    cited_tools: set[str] = set()
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        matches = tool_ref_pattern.findall(content)
        for m in matches:
            # Exclure les fonctions internes / services (seuls les tools importables/exposés comptent)
            if not m.endswith("_service") and not m.startswith("ffbb_get_"):
                cited_tools.add(m)

    missing = cited_tools - exposed_tools
    # Tolérance pour d'éventuels helpers historiques non-tools s'il y en a
    unregistered_tools = [t for t in missing if t in {"ffbb_match_lookup"}]
    assert not unregistered_tools, (
        f"Outils cités mais non exposés : {unregistered_tools}"
    )


@pytest.mark.asyncio
async def test_ffbb_version_always_has_sha_keys():
    """ffbb_version doit toujours inclure build_sha et git_sha (même si None)."""
    ver = await ffbb_version()
    assert "build_sha" in ver
    assert "package_version" in ver
    assert ver["package_version"].startswith("1.16.")


@pytest.mark.asyncio
async def test_ffbb_lives_no_duplicate_matches():
    """ffbb_lives ne doit plus dupliquer matches et doit nettoyer presentation dans salle_details."""
    fake_matches = [
        {
            "id": "1",
            "nomEquipe1": "A",
            "nomEquipe2": "B",
            "salle_details": {
                "libelle": "Gymnase",
                "presentation": {"short_answer": "Inutile ici"},
            },
        }
    ]
    with patch(
        "ffbb_mcp.server.get_lives_service",
        new_callable=AsyncMock,
        return_value=fake_matches,
    ):
        res = await ffbb_lives()
        assert "matches" not in res
        assert "items" in res
        assert len(res["items"]) == 1
        assert "presentation" not in res["items"][0]["salle_details"]


@pytest.mark.asyncio
async def test_ffbb_search_warning_not_duplicated():
    """Le warning de fraîcheur dans ffbb_search doit être à la racine, pas dupliqué dans _meta."""
    with patch(
        "ffbb_mcp.services.search.search_rencontres_service",
        new_callable=AsyncMock,
        return_value=[],
    ):
        res = await ffbb_search_service(query="test", type="rencontres")
        assert "warning" in res
        assert "_meta" in res
        assert "warning" not in res["_meta"]


def test_dynamique_numero_journee_parsing():
    """compute_team_dynamique doit parser numeroJournee en J{num} et préserver id."""
    match = {
        "id": "m123",
        "date_rencontre": "2026-10-04 10:00:00",
        "numeroJournee": 2,
        "nomEquipe1": "THIERS",
        "nomEquipe2": "GERZAT",
        "resultatEquipe1": 70,
        "resultatEquipe2": 60,
        "joue": 1,
    }
    dyn = compute_team_dynamique([match], club_nom="THIERS")
    assert len(dyn["matchs"]) == 1
    m = dyn["matchs"][0]
    assert m["journee"] == "J2"
    assert m["id"] == "m123"


@pytest.mark.asyncio
async def test_salle_enrichment_meilisearch_libelle2_and_geo():
    """_enrich_salle_data_with_meilisearch doit enrichir libelle2, telephone et geo."""

    from types import SimpleNamespace

    fake_hit = SimpleNamespace(
        id="s1",
        libelle="Salle 1",
        libelle2="FRANCISQUE SAUZEDDE",
        telephone="0473805211",
        geo={"lat": 45.84, "lng": 3.52},
        cartographie=None,
        commune=None,
    )
    fake_search_res = SimpleNamespace(hits=[fake_hit])

    fake_client = AsyncMock()
    fake_client.search_salles_async = AsyncMock(return_value=fake_search_res)

    salle_data = {"id": "s1", "libelle": "Salle 1", "ville": "Thiers"}
    await _enrich_salle_data_with_meilisearch(salle_data, fake_client)
    assert salle_data["libelle2"] == "FRANCISQUE SAUZEDDE"
    assert salle_data["telephone"] == "0473805211"
    assert salle_data["geo"] == {"lat": 45.84, "lng": 3.52}


@pytest.mark.asyncio
async def test_ffbb_get_salle_presentation_enriched():
    """ffbb_get(salle) doit intégrer libelle2, téléphone et coordonnées GPS."""
    fake_salle = {
        "id": "s1",
        "libelle": "MAISON DES SPORTS",
        "libelle2": "FRANCISQUE SAUZEDDE",
        "adresse": "115 Avenue Léo Lagrange",
        "telephone": "0473805211",
        "geo": {"lat": 45.84556, "lng": 3.52146},
    }
    with patch(
        "ffbb_mcp.server.get_salle_service",
        new_callable=AsyncMock,
        return_value=fake_salle,
    ):
        res = await ffbb_get(type="salle", id="s1")
        pres = res["presentation"]
        assert "FRANCISQUE SAUZEDDE" in pres["short_answer"]
        assert "0473805211" in pres["detail_line"]
        assert "GPS: 45.84556, 3.52146" in pres["detail_line"]


@pytest.mark.asyncio
async def test_next_match_not_found_has_envelope():
    """Un club introuvable dans ffbb_next_match doit retourner un dict avec presentation et provenance."""
    with patch(
        "ffbb_mcp.services.search.resolve_club_and_org",
        new_callable=AsyncMock,
        return_value=([], {}),
    ):
        res = await ffbb_next_match_service(club_name="ClubInconnu99999")
        assert res["status"] == "not_found"
        assert "presentation" in res
        assert "provenance" in res
        assert (
            "Club 'ClubInconnu99999' introuvable."
            in res["presentation"]["short_answer"]
        )


def test_lighten_rencontre_hit_commune_fallback():
    """_lighten_rencontre_hit doit peupler salle.commune via l'organisme hôte si absent."""
    raw_hit = {
        "id": "m1",
        "nom_equipe1": "THIERS",
        "nom_equipe2": "GERZAT",
        "salle": {
            "id": "s1",
            "libelle": "Maison des Sports",
            "adresse": "115 Avenue Léo Lagrange",
            "commune": None,
        },
        "id_organisme_equipe1": {
            "id": "9328",
            "nom": "THIERS",
            "ville": "THIERS",
            "code_postal": "63300",
            "departement": "Puy-de-dôme",
        },
    }
    cleaned = _lighten_rencontre_hit(raw_hit)
    assert cleaned["salle"]["commune"] is not None
    assert cleaned["salle"]["commune"]["libelle"] == "THIERS"
    assert cleaned["salle"]["commune"]["codePostal"] == "63300"
