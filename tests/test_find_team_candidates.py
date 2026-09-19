import pytest
from mcp.shared.exceptions import McpError

from ffbb_mcp.server import ffbb_find_team_candidates
from ffbb_mcp.services.search import ffbb_find_team_candidates_service


@pytest.fixture
def cournon_teams():
    return [
        {
            "engagement_id": "200000005346869",
            "team_id": "200000005346869",
            "poule_id": "200000003058000",
            "team_label": "U13F",
            "nom_equipe": "IE - CTC CLERMONT SUD GERGOVIE BASKET - BB COURNON D'AUVERGNE",
            "numero_equipe": None,
            "competition": "RFU13 Brassage",
            "competition_type": "PLAT",
            "categorie": "U13",
            "sexe": "F",
            "niveau": "régional",
        },
        {
            "engagement_id": "200000005358422",
            "team_id": "200000005358422",
            "poule_id": "200000003059000",
            "team_label": "U13F2",
            "nom_equipe": "IE - CTC CLERMONT SUD GERGOVIE BASKET - BB COURNON D'AUVERGNE - 2",
            "numero_equipe": "2",
            "competition": "Départementale féminine U13",
            "competition_type": "DIV",
            "categorie": "U13",
            "sexe": "F",
            "niveau": "départemental",
        },
        {
            "engagement_id": "200000005346999",
            "team_id": "200000005346999",
            "poule_id": "200000003059999",
            "team_label": "U15M",
            "nom_equipe": "BB COURNON D'AUVERGNE",
            "numero_equipe": "1",
            "competition": "DMU15",
            "competition_type": "DIV",
            "categorie": "U15",
            "sexe": "M",
            "niveau": "départemental",
        },
    ]


@pytest.fixture(autouse=True)
def setup_candidates_mocks(cournon_teams, monkeypatch):
    async def mock_resolve(
        club_name=None,
        organisme_id=None,
        categorie=None,
        limit=5,
        force_refresh=False,
    ):
        if club_name and "inexistant" in club_name.lower():
            return [], None
        return (
            [
                {
                    "organisme_id": "9289",
                    "nom": "BB COURNON D'AUVERGNE",
                    "commune": "Cournon-d'Auvergne",
                }
            ],
            None,
        )

    async def mock_equipes(organisme_id, force_refresh=False, season_id=None):
        if str(organisme_id) == "9289":
            return cournon_teams
        return []

    async def mock_fetch_matches(
        teams, organisme_nom=None, numero_equipe=None, force_refresh=False
    ):
        return [
            (
                {
                    "date_rencontre": "2026-10-15",
                    "heure": "14:00",
                    "nomEquipe1": "IE - CTC CLERMONT SUD GERGOVIE BASKET - BB COURNON D'AUVERGNE",
                    "nomEquipe2": "AS MONTIER",
                    "nomSalle": "Gymnase de Cournon",
                },
                {},
            )
        ]

    monkeypatch.setattr("ffbb_mcp.services.search.resolve_club_and_org", mock_resolve)
    monkeypatch.setattr("ffbb_mcp.services.ffbb_equipes_club_service", mock_equipes)
    monkeypatch.setattr(
        "ffbb_mcp.services.club.ffbb_equipes_club_service", mock_equipes
    )
    monkeypatch.setattr("ffbb_mcp.services._fetch_poule_matches", mock_fetch_matches)


@pytest.mark.asyncio
async def test_find_team_candidates_cournon_u13f1_ambiguous():
    """Vérifie le cas réel : 'U13F1 Cournon'.

    Doit retourner deux candidats distincts :
    1. U13F (RFU13 Brassage, engagement_id='200000005346869', équipe sans numéro FFBB explicite)
    2. U13F2 (Départementale féminine U13, engagement_id='200000005358422', équipe n°2)
    Et le statut doit être 'ambiguous' sans substitution silencieuse.
    """
    res = await ffbb_find_team_candidates_service(
        club_name="Cournon",
        categorie="U13F1",
    )

    assert res["status"] == "ambiguous"
    assert res["total_candidates"] == 2
    candidates = res["candidates"]

    c1 = candidates[0]
    assert c1["engagement_id"] == "200000005346869"
    assert c1["team_label"] == "U13F"
    assert c1["numero_equipe"] is None
    assert "RFU13" in c1["competition_name"]
    assert "régional" in c1["niveau"]
    assert c1["match_confidence"] >= 0.8
    assert "Équipe principale sans numéro explicite" in c1["match_reason"]

    c2 = candidates[1]
    assert c2["engagement_id"] == "200000005358422"
    assert c2["team_label"] == "U13F2"
    assert c2["numero_equipe"] == 2
    assert "Départementale" in c2["competition_name"]
    assert c2["niveau"] == "départemental"
    assert c2["match_confidence"] <= 0.7
    assert "équipe distincte n°2" in c2["match_reason"]

    # Vérification du prompt de clarification
    prompt = res["clarification_prompt"]
    assert prompt is not None
    assert "## Équipes candidates" in prompt
    assert "200000005346869" in prompt
    assert "200000005358422" in prompt
    assert "Laquelle souhaites-tu consulter ?" in prompt


@pytest.mark.asyncio
async def test_find_team_candidates_cournon_u13f_exact_label():
    """Vérifie que pour 'U13F', l'équipe U13F a une confiance de 0.95."""
    res = await ffbb_find_team_candidates_service(
        organisme_id="9289",
        categorie="U13F",
    )

    assert res["total_candidates"] >= 2
    c1 = res["candidates"][0]
    assert c1["team_label"] == "U13F"
    assert c1["match_confidence"] == 0.95
    assert "Libellé FFBB exact" in c1["match_reason"]

    c2 = res["candidates"][1]
    assert c2["team_label"] == "U13F2"
    assert c2["match_confidence"] == 0.70


@pytest.mark.asyncio
async def test_find_team_candidates_strict_age_isolation():
    """Vérifie que la recherche U13 n'inclut aucune équipe U11, U15 ou U18."""
    res = await ffbb_find_team_candidates_service(
        organisme_id="9289",
        categorie="U13",
    )

    assert res["total_candidates"] > 0
    for c in res["candidates"]:
        assert "U13" in c["team_label"]
        assert "U11" not in c["team_label"]
        assert "U15" not in c["team_label"]
        assert "U18" not in c["team_label"]


@pytest.mark.asyncio
async def test_find_team_candidates_missing_club_raises():
    """Vérifie qu'un appel sans club_name ni organisme_id lève McpError."""
    with pytest.raises(McpError):
        await ffbb_find_team_candidates_service()


@pytest.mark.asyncio
async def test_find_team_candidates_club_not_found():
    """Vérifie qu'un club inconnu renvoie not_found."""
    res = await ffbb_find_team_candidates_service(
        club_name="ClubInexistantXYZ123456789",
        categorie="U13F",
    )
    assert res["status"] == "not_found"
    assert len(res["candidates"]) == 0


@pytest.mark.asyncio
async def test_server_tool_ffbb_find_team_candidates():
    """Vérifie que l'outil FastAPI / FastMCP est correctement branché."""
    res = await ffbb_find_team_candidates(
        organisme_id="9289",
        categorie="U13F1",
    )
    assert res["status"] == "ambiguous"
    assert len(res["candidates"]) == 2
