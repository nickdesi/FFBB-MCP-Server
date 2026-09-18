"""Tests unitaires pour le moteur de règlements FFBB et les outils MCP associés."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ffbb_mcp.regulations.engine import (
    RegulationsEngine,
    _sanitize_fts5_query,
)
from ffbb_mcp.regulations.indexer import (
    index_manifest,
)
from ffbb_mcp.server import (
    ffbb_explain_tiebreak_rules,
    ffbb_get_regulation_article,
    ffbb_list_regulations,
    ffbb_search_regulations,
)
from ffbb_mcp.services.regulations import (
    explain_tiebreak_rules_service,
    get_regulation_article_service,
    list_regulations_service,
    search_regulations_service,
)


@pytest.fixture
def manifest_path() -> Path:
    base_dir = Path(__file__).parent.parent / "data" / "regulations"
    return base_dir / "manifest.yaml"


@pytest.fixture
def memory_engine(manifest_path: Path):
    """Instancie un moteur FTS5 en mémoire pour les tests."""
    engine = RegulationsEngine(db_path=None, manifest_path=manifest_path)
    yield engine
    engine.close()


def test_sanitize_fts5_query():
    """Vérifie le nettoyage et formatage des requêtes FTS5."""
    assert _sanitize_fts5_query("défense de zone") == '"défense"* OR "de"* OR "zone"*'
    assert _sanitize_fts5_query("Article 28!") == '"Article"* OR "28"*'
    assert _sanitize_fts5_query("") == ""
    assert _sanitize_fts5_query("   ") == ""


def test_manifest_indexing(manifest_path: Path):
    """Vérifie que tous les documents du manifeste sont indexés à l'échelle nationale."""
    conn = sqlite3.connect(":memory:")
    total = index_manifest(manifest_path, conn=conn)
    assert total > 0

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM regulation_articles")
    count = cursor.fetchone()[0]
    assert count == total
    assert (
        count >= 20
    )  # Plus de 20 articles déclarés (fédéral, idf, hdf, aura, paris, nord, rhone, 63)
    conn.close()


def test_search_regulations_accents_and_ranking(memory_engine: RegulationsEngine):
    """Vérifie la recherche avec accents (défense, brûlage, départage)."""
    # 1. Recherche "défense de zone"
    res_zone = memory_engine.search(query="défense de zone", limit=5)
    assert len(res_zone) > 0
    contents = [r.article.content for r in res_zone]
    assert any("zone" in c and "interdite" in c for c in contents)

    # 2. Recherche "brûlage"
    res_brulage = memory_engine.search(query="brûlage", limit=5)
    assert len(res_brulage) > 0
    contents = [r.article.content for r in res_brulage]
    assert any(
        "brûlé" in c or "brûlage" in c or "feuille de match" in c for c in contents
    )


def test_search_regulations_national_coverage(memory_engine: RegulationsEngine):
    """Vérifie la couverture multi-régionale et fédérale (NM1/NM2/NM3, IDF, Hauts-de-France, Paris, Nord, Rhône)."""
    # 1. Fédéral Seniors NM1 (Accession Pro B)
    res_nm1 = memory_engine.search(
        query="accession Pro B",
        level="federal",
        category="NM1",
    )
    assert len(res_nm1) > 0
    assert any("NM1" in r.article.content for r in res_nm1)

    # 2. Régional Île-de-France (LIFBB)
    res_idf = memory_engine.search(
        query="LIFBB divisions seniors",
        organizer="Ligue Île-de-France",
    )
    assert len(res_idf) > 0
    assert any("Île-de-France" in r.article.organizer for r in res_idf)

    # 3. Départemental Paris (Basket 75)
    res_paris = memory_engine.search(
        query="règles jeunes U13",
        organizer="Comité Paris",
    )
    assert len(res_paris) > 0
    assert any("Paris" in r.article.organizer for r in res_paris)

    # 4. Départemental Nord (Basket 59)
    res_nord = memory_engine.search(
        query="brassages jeunes",
        organizer="Comité Nord",
    )
    assert len(res_nord) > 0
    assert any("Nord" in r.article.organizer for r in res_nord)

    # 5. Départemental Rhône (Basket 69)
    res_rhone = memory_engine.search(
        query="règles techniques U13",
        organizer="Comité Rhône",
    )
    assert len(res_rhone) > 0
    assert any("Rhône" in r.article.organizer for r in res_rhone)

    # 6. Départemental Allier (Basket 03)
    res_allier = memory_engine.search(
        query="brassages Allier U13",
        organizer="Comité 03",
    )
    assert len(res_allier) > 0
    assert any(
        "03" in r.article.organizer or "Allier" in r.article.organizer
        for r in res_allier
    )


def test_search_regulations_fallback_to_federal(memory_engine: RegulationsEngine):
    """Vérifie le fallback automatique sur le RSG fédéral si un comité non indexé est demandé."""
    # Requête pour un comité non localement référencé (ex: Comité 99 Inconnu)
    res_fallback = memory_engine.search(
        query="forfait général relégation deux divisions",
        organizer="Comité Inconnu 99",
    )
    assert len(res_fallback) > 0
    # Doit remonter l'article 20 du RSG FFBB grâce au fallback
    assert any("Article 20" in r.article.article_number for r in res_fallback)


def test_get_exact_article(memory_engine: RegulationsEngine):
    """Vérifie l'extraction exacte d'un article par numéro."""
    # Article 28 du RSG FFBB
    art28 = memory_engine.get_article(
        document_id="rsg_ffbb_2026_2027",
        article_number="Article 28",
    )
    assert art28 is not None
    assert "Article 28" in art28.article_number
    assert "point-average particulier" in art28.content
    assert "mini-championnat" in art28.content

    # Article 51 du RSG (brûlage)
    art51 = memory_engine.get_article(
        document_id="rsg_ffbb_2026_2027",
        article_number="51",
    )
    assert art51 is not None
    assert "Article 51" in art51.article_number

    # Article inexistant
    art_none = memory_engine.get_article(
        document_id="rsg_ffbb_2026_2027",
        article_number="Article 9999",
    )
    assert art_none is None


@pytest.mark.asyncio
async def test_regulations_services():
    """Vérifie la couche service asynchrone."""
    # 1. Service de recherche
    search_res = await search_regulations_service(
        query="forfait général relégation",
        season="2026-2027",
    )
    assert search_res["total_results"] > 0
    assert any("Article 20" in r["article_number"] for r in search_res["results"])

    # 2. Service d'extraction d'article
    art_res = await get_regulation_article_service(
        document_id="rsg_ffbb_2026_2027",
        article_number="Article 28",
    )
    assert art_res["found"] is True
    assert "Article 28" in art_res["article"]["article_number"]

    # 3. Service d'explication du départage
    tb_res = await explain_tiebreak_rules_service(poule_id=12345)
    assert "Article 28" in tb_res["regulation_source"]
    assert "point-average particulier" in tb_res["summary"]
    assert tb_res["poule_id"] == 12345

    # 4. Service d'inventaire national
    list_res = await list_regulations_service(season="2026-2027")
    assert list_res["scope"] == "national"
    assert list_res["total_documents"] >= 7
    organizers = [j["organizer"] for j in list_res["jurisdictions"]]
    assert "FFBB" in organizers
    assert "Ligue Île-de-France" in organizers


@pytest.mark.asyncio
async def test_mcp_regulation_tools():
    """Vérifie les outils FastMCP directement."""
    # Test ffbb_search_regulations
    res_search = await ffbb_search_regulations(
        query="Poule Haute U13 brassages",
        organizer="Comité 63",
    )
    assert isinstance(res_search, dict)
    assert res_search.get("total_results", 0) > 0

    # Test ffbb_get_regulation_article
    res_art = await ffbb_get_regulation_article(
        article_number="Article 7",
        organizer="Comité 63",
    )
    assert res_art.get("found") is True
    assert "Article 7" in res_art["article"]["article_number"]

    # Test ffbb_explain_tiebreak_rules
    res_tb = await ffbb_explain_tiebreak_rules(poule_id=9876)
    assert "point-average" in res_tb["summary"]

    # Test ffbb_list_regulations
    res_list = await ffbb_list_regulations(season="2026-2027")
    assert res_list.get("total_documents", 0) >= 7


def test_missing_manifest_engine_initialization(tmp_path: Path):
    """Vérifie que RegulationsEngine crée le schéma sans crasher même sans manifeste."""
    fake_manifest = tmp_path / "non_existent_manifest.yaml"
    engine = RegulationsEngine(manifest_path=fake_manifest)
    try:
        # La table doit exister sans lever d'OperationalError
        assert engine.search("départage") == []
        assert engine.get_article("rsg", "Article 28") is None
        assert engine.list_available_documents() == []
    finally:
        engine.close()


def test_find_default_manifest_path():
    """Vérifie que la découverte automatique trouve le manifeste embarqué ou racine."""
    from ffbb_mcp.regulations.engine import find_default_manifest_path

    manifest = find_default_manifest_path()
    assert manifest is not None
    assert manifest.exists()
    assert manifest.name == "manifest.yaml"


@pytest.mark.asyncio
async def test_search_regulations_scoring_brulage():
    """Vérifie que l'article 51 (brûlage) est classé avant l'article 12 pour une requête sur le brûlage."""
    res = await ffbb_search_regulations(
        query="brulage equipe reserve joueur",
        level="federal",
        limit=5,
    )
    assert isinstance(res, dict)
    results = res.get("results") or []
    assert len(results) >= 2

    # L'article 51 doit être en tête devant l'article 12
    first_art = results[0]
    assert "Article 51" in first_art["article_number"]
    assert "brûlage" in first_art["article_title"].lower()

    # Vérification de la présence et du contenu du champ topics
    for r in results:
        assert "topics" in r
        assert isinstance(r["topics"], list)
        assert len(r["topics"]) > 0
