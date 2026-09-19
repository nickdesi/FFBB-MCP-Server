"""Tests unitaires pour la fiabilité et la traçabilité du module réglementaire."""

from __future__ import annotations

import pytest

from ffbb_mcp.regulations.applicability import (
    LOCAL_NOT_INDEXED_WARNING,
    OFFICIAL_DISCLAIMER,
    is_sensitive_topic,
    resolve_applicable_regulations,
)
from ffbb_mcp.regulations.engine import RegulationsEngine
from ffbb_mcp.regulations.models import RegulationArticle


@pytest.fixture
def memory_engine():
    """Crée un moteur éphémère avec quelques articles de test multi-niveaux."""
    engine = RegulationsEngine(db_path=None)
    cursor = engine._conn.cursor()

    # Article Fédéral (RSG)
    cursor.execute(
        """
        INSERT INTO regulation_articles (
            id, document_id, season, level, organizer, categories,
            article_number, article_title, content, topics, source_url
        ) VALUES (
            'art_rsg_28', 'rsg_ffbb_2026_2027', '2026-2027', 'federal', 'FFBB', '["toutes"]',
            'Article 28', 'Classement et départage', 'En cas d''égalité de points, le départage s''opère au quotient...',
            'classement,egalite,departage,point-average', 'https://www.ffbb.com/reglements'
        )
        """
    )

    # Article Régional (AURA)
    cursor.execute(
        """
        INSERT INTO regulation_articles (
            id, document_id, season, level, organizer, categories,
            article_number, article_title, content, topics, source_url
        ) VALUES (
            'art_aura_15', 'reg_aura_2026_2027', '2026-2027', 'regional', 'Ligue AURA', '["seniors"]',
            'Article 15', 'Brûlage et qualification des joueurs', 'Un joueur ayant participé à 5 rencontres de NM3 est brûlé...',
            'brulage,licence,qualification', 'https://www.aurabasketball.org/reglements'
        )
        """
    )

    engine._conn.commit()
    yield engine
    engine.close()


def test_regulation_document_has_official_source_and_hash():
    """Vérifie la génération automatique du hash SHA-256 et la source officielle."""
    art = RegulationArticle(
        id="test_art_1",
        document_id="rsg_2026",
        season="2026-2027",
        level="federal",
        organizer="FFBB",
        article_number="Article 1",
        article_title="Dispositions Générales",
        content="Le présent règlement s'applique à l'ensemble du territoire français.",
        official_source_url="https://www.ffbb.com/doc.pdf",
    )

    assert art.content_hash.startswith("sha256:")
    assert len(art.content_hash) > 10
    assert art.official_source_url == "https://www.ffbb.com/doc.pdf"


def test_regulation_document_has_season_and_jurisdiction():
    """Vérifie la présence de la saison et de la juridiction."""
    art = RegulationArticle(
        id="test_art_2",
        document_id="rsg_2026",
        season="2026-2027",
        level="federal",
        organizer="FFBB",
        jurisdiction="France",
        article_number="Article 2",
        article_title="Objet",
        content="Organisation du basket.",
    )

    assert art.season == "2026-2027"
    assert art.jurisdiction == "France"


def test_regulation_search_returns_level_and_organizer(memory_engine):
    """Vérifie que la recherche renvoie les métadonnées de niveau et d'organisateur."""
    results = memory_engine.search("départage", season="2026-2027")
    assert len(results) > 0
    first_art = results[0].article
    assert first_art.level == "federal"
    assert first_art.organizer == "FFBB"


def test_regulation_response_warns_when_local_rule_is_not_indexed(memory_engine):
    """Vérifie l'avertissement explicite quand un règlement local demandé n'est pas indexé."""
    context = {
        "season": "2026-2027",
        "departement": "Comité 75 Paris",
    }
    res = resolve_applicable_regulations(context=context, engine=memory_engine)

    assert LOCAL_NOT_INDEXED_WARNING in res["warnings"]


def test_applicable_regulations_respect_hierarchy(memory_engine):
    """Vérifie le respect de la hiérarchie officielle : fédéral en premier, puis régional."""
    context = {
        "season": "2026-2027",
        "region": "AURA",
    }
    res = resolve_applicable_regulations(context=context, engine=memory_engine)

    articles = res["articles"]
    assert len(articles) >= 2
    levels = [a["level"] for a in articles]
    assert "federal" in levels
    assert "regional" in levels
    first_reg_idx = levels.index("regional")
    assert first_reg_idx > 0
    # Tous les articles précédant le premier régional doivent impérativement être fédéraux
    for lvl in levels[:first_reg_idx]:
        assert lvl == "federal"


def test_sensitive_regulation_topics_include_disclaimer(memory_engine):
    """Vérifie l'injection obligatoire du disclaimer officiel pour les sujets sensibles."""
    assert is_sensitive_topic("brûlage des joueurs") is True
    assert is_sensitive_topic("question sur les forfaits et pénalités") is True
    assert is_sensitive_topic("horaire de la rencontre") is False

    context = {
        "season": "2026-2027",
    }
    res = resolve_applicable_regulations(
        context=context,
        query="brûlage et qualification de joueur",
        engine=memory_engine,
    )

    assert res["is_sensitive_topic"] is True
    assert OFFICIAL_DISCLAIMER in res["warnings"]
    assert res["disclaimer"] == OFFICIAL_DISCLAIMER
