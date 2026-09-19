"""Tests de non-régression stricts pour l'alignement de ffbb-api sur les codes et libellés réels."""

from __future__ import annotations

import pytest

from ffbb_mcp.competition_type import (
    format_competition_display,
    format_competition_technical_detail,
    resolve_competition_type,
    resolve_practice,
)


def test_1_rfu13_brassage_undocumented_or_raw_fallback():
    """Test 1 — RFU13 Brassage : Aucun libellé officiel FFBB récupéré / fallback.

    Quand aucun libellé officiel n'est validé, le MCP retourne :
    competition_type.code = "PLAT", label = None, documented = False.
    Et le rendu utilisateur doit être : 'RFU13 Brassage — Poule A — Basket 5×5'.
    Il ne doit contenir ni 'plateau', ni 'format plateau', ni aucune interprétation de PLAT.
    """
    comp_input = {
        "competition_name": "RFU13 Brassage",
        "competition_id": "200000002898047",
        "poule_name": "Poule A",
        "poule_id": "200000003056266",
        "competition_type_code": "PLAT",
        "practice": "5x5",
    }

    # Simulation sans mapping officiel
    type_info = resolve_competition_type(
        comp_input["competition_type_code"],
        allow_official_mapping=False,
    )

    assert type_info.code == "PLAT"
    assert type_info.label is None
    assert type_info.documented is False

    practice_info = resolve_practice(comp_input["practice"])
    rendered = format_competition_display(
        competition_name=comp_input["competition_name"],
        poule_name=comp_input["poule_name"],
        practice=practice_info,
    )

    # Rendu attendu exact
    assert rendered == "RFU13 Brassage — Poule A — Basket 5×5"

    # Vérifications négatives strictes
    assert "plateau" not in rendered.lower()
    assert "format" not in rendered.lower()
    assert "PLAT" not in rendered

    # Vérification du détail technique
    tech_str = format_competition_technical_detail(type_info)
    assert "Code technique FFBB : PLAT" in tech_str
    assert "Libellé officiel associé : non documenté dans ffbb-api" in tech_str


def test_2_official_mapping_directus_reference():
    """Test 2 — Mapping officiel trouvé dans ffbb-api (Directus schema metadata).

    Source officielle : GET https://api.ffbb.app/fields/ffbbserver_competitions/typeCompetition
    L'API Directus expose la liste des choix officiels :
    - DIV -> Championnat
    - COUPE -> Coupe
    - PLAT -> Plateau
    - DIV_3x3 -> Championnat 3x3
    """
    type_info = resolve_competition_type("PLAT", allow_official_mapping=True)

    assert type_info.code == "PLAT"
    assert type_info.label == "Plateau"
    assert type_info.source == "fields/ffbbserver_competitions/typeCompetition"
    assert type_info.documented is True

    # Vérification des autres choix officiels
    div_info = resolve_competition_type("DIV")
    assert div_info.label == "Championnat"
    assert div_info.documented is True

    coupe_info = resolve_competition_type("COUPE")
    assert coupe_info.label == "Coupe"
    assert coupe_info.documented is True

    div3x3_info = resolve_competition_type("DIV_3x3")
    assert div3x3_info.label == "Championnat 3x3"
    assert div3x3_info.documented is True

    # Même avec mapping officiel, le rendu utilisateur reste fidèle au nom métier et à la poule
    rendered = format_competition_display(
        competition_name="RFU13 Brassage",
        poule_name="Poule A",
        practice="5x5",
    )
    assert rendered == "RFU13 Brassage — Poule A — Basket 5×5"
    assert "format plateau" not in rendered.lower()

    tech_str = format_competition_technical_detail(type_info)
    assert "Code technique FFBB : PLAT" in tech_str
    assert "Plateau" in tech_str
    assert "fields/ffbbserver_competitions/typeCompetition" in tech_str


def test_3_raw_data_preservation():
    """Test 3 — Conservation absolue des données brutes FFBB.

    - Le code FFBB brut 'PLAT' doit être conservé.
    - Le libellé original 'RFU13 Brassage ' (ou stripped) doit être conservé.
    - Aucune transformation ne doit écraser ou remplacer les données source.
    - Le champ technique ne doit jamais supplanter competition.name.
    """
    raw_competition_name = "RFU13 Brassage "
    raw_comp_code = "PLAT"
    raw_poule_name = "Poule A"
    raw_practice = "5x5"

    type_info = resolve_competition_type(raw_comp_code)

    # 1. Code brut conservé
    assert type_info.code == "PLAT"

    # 2. Nom de compétition préservé
    assert raw_competition_name.strip() == "RFU13 Brassage"

    # 3. Le champ technique ne supplante pas le nom
    display = format_competition_display(
        competition_name=raw_competition_name,
        poule_name=raw_poule_name,
        practice=raw_practice,
    )
    assert display.startswith("RFU13 Brassage")
    assert "Poule A" in display
    assert "Basket 5×5" in display


def test_unknown_technical_code_remains_undocumented():
    """Vérifie qu'un code technique imaginaire ou non répertorié ne provoque aucune supposition."""
    unknown = resolve_competition_type("FORMAT_INCONNU_123")
    assert unknown.code == "FORMAT_INCONNU_123"
    assert unknown.label is None
    assert unknown.documented is False

    tech = format_competition_technical_detail(unknown)
    assert "Code technique FFBB : FORMAT_INCONNU_123" in tech
    assert "Libellé officiel associé : non documenté dans ffbb-api" in tech


@pytest.mark.asyncio
async def test_calendar_service_integration_rfu13_brassage(monkeypatch):
    """Vérifie que le service de calendrier produit fidèlement les métadonnées de compétition, poule et pratique."""
    from unittest.mock import AsyncMock

    from ffbb_mcp.services.calendar import _build_calendar_matches

    poule_mock = {
        "id": "200000003056266",
        "nom": "Poule A",
        "rencontres": [
            {
                "id": "200000014577497",
                "date_rencontre": "2026-09-19 13:30:00",
                "pratique": "5x5",
                "nomEquipe1": "CRAP DE VEAUCHE",
                "nomEquipe2": "IE - CTC CLERMONT SUD GERGOVIE BASKET - BB COURNON D'AUVERGNE",
                "idEngagementEquipe1": "999",
                "idEngagementEquipe2": "200000005346869",
                "resultatEquipe1": "20",
                "resultatEquipe2": "97",
                "joue": 1,
            }
        ],
    }

    equipe_mock = {
        "engagement_id": "200000005346869",
        "team_label": "U13F",
        "nom_equipe": "IE - CTC CLERMONT SUD GERGOVIE BASKET - BB COURNON D'AUVERGNE",
        "competition": "RFU13 Brassage ",
        "competition_id": "200000002898047",
        "competition_type": "PLAT",
        "poule_id": "200000003056266",
    }

    monkeypatch.setattr(
        "ffbb_mcp.services.search.resolve_club_and_org",
        AsyncMock(
            return_value=(
                [{"organisme_id": "9289", "nom": "BB COURNON D'AUVERGNE"}],
                None,
            )
        ),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.ffbb_equipes_club_service",
        AsyncMock(return_value=[equipe_mock]),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service",
        AsyncMock(return_value=[equipe_mock]),
    )
    monkeypatch.setattr(
        "ffbb_mcp.services.poule.get_poule_service",
        AsyncMock(return_value=poule_mock),
    )

    res = await _build_calendar_matches(
        club_name="Cournon",
        organisme_id="9289",
        categorie="U13F",
        numero_equipe=None,
        adversaire=None,
        date_debut=None,
        date_fin=None,
        limit=50,
        engagement_id="200000005346869",
    )

    items = res.get("items") or []
    assert len(items) == 1
    m = items[0]

    # Données brutes fidèles
    assert m["competition_name"] == "RFU13 Brassage"
    assert m["competition_type"] == "PLAT"
    assert m["competition_type_code"] == "PLAT"

    # Données enrichies officielles
    assert m["competition_type_detail"]["label"] == "Plateau"
    assert m["competition_type_detail"]["documented"] is True
    assert (
        m["competition_type_detail"]["source"]
        == "fields/ffbbserver_competitions/typeCompetition"
    )

    # Poule & Pratique officielles
    assert m["poule_nom"] == "Poule A"
    assert m["pratique"] == "Basket 5×5"
    assert m["pratique_code"] == "5x5"

    # Rendu d'affichage canonique
    assert m["competition_display"] == "RFU13 Brassage — Poule A — Basket 5×5"
    assert "format plateau" not in m["competition_display"].lower()
