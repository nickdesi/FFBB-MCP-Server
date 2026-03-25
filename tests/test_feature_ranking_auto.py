from unittest.mock import AsyncMock, MagicMock

import pytest

from ffbb_mcp.services import ffbb_get_classement_service, resolve_poule_id_service


@pytest.mark.asyncio
async def test_resolve_poule_id_service_by_phase(monkeypatch):
    """Vérifie que la résolution par phase fonctionne (Phase 2)."""

    mock_equipes = [
        {
            "poule_id": "p1",
            "competition": "Dep U11M Phase 1",
            "phase_label": "Phase 1",
            "niveau": 1,
        },
        {
            "poule_id": "p2",
            "competition": "Dep U11M Phase 2",
            "phase_label": "Phase 2",
            "niveau": 2,
        },
        {
            "poule_id": "p3",
            "competition": "Dep U11M Phase 3",
            "phase_label": "Phase 3",
            "niveau": 3,
        },
    ]

    async def mock_equipes_service(organisme_id, filtre):
        return mock_equipes

    monkeypatch.setattr(
        "ffbb_mcp.services.ffbb_equipes_club_service", mock_equipes_service
    )

    # Test matching "phase 2"
    pid = await resolve_poule_id_service(
        organisme_id=123, categorie="U11M", phase_query="phase 2"
    )
    assert pid == "p2"

    # Test matching "3"
    pid = await resolve_poule_id_service(
        organisme_id=123, categorie="U11M", phase_query="3"
    )
    assert pid == "p3"


@pytest.mark.asyncio
async def test_resolve_poule_id_service_default_to_latest(monkeypatch):
    """Vérifie que sans phase, on prend la phase au niveau le plus haut."""

    mock_equipes = [
        {"poule_id": "p1", "competition": "Dep U11M Phase 1", "niveau": 1},
        {"poule_id": "p3", "competition": "Dep U11M Phase 3", "niveau": 3},
        {"poule_id": "p2", "competition": "Dep U11M Phase 2", "niveau": 2},
    ]

    async def mock_equipes_service(organisme_id, filtre):
        return mock_equipes

    monkeypatch.setattr(
        "ffbb_mcp.services.ffbb_equipes_club_service", mock_equipes_service
    )

    pid = await resolve_poule_id_service(organisme_id=123, categorie="U11M")
    assert pid == "p3"


@pytest.mark.asyncio
async def test_ffbb_get_classement_service_highlighting(monkeypatch):
    """Vérifie que l'équipe cible est bien marquée via is_target."""

    # Mock client and data
    mock_poule = MagicMock()
    mock_poule.model_dump.return_value = {
        "classements": [
            {
                "position": 1,
                "organisme_id": "org1",
                "id_engagement": {"nom": "EQ 1", "numero_equipe": "1"},
            },
            {
                "position": 2,
                "organisme_id": "org2",
                "id_engagement": {"nom": "EQ 2", "numero_equipe": "1"},
            },
        ]
    }

    mock_client = MagicMock()
    mock_client.get_poule_async = AsyncMock(return_value=mock_poule)

    async def mock_get_client():
        return mock_client

    monkeypatch.setattr("ffbb_mcp.services.get_client_async", mock_get_client)

    # Clear cache for test consistency if needed (though new key should be fine)

    # Test highlighting org2
    res = await ffbb_get_classement_service(
        poule_id="123", target_organisme_id="org2", target_num="1"
    )

    assert len(res) == 2
    assert res[0]["is_target"] is False
    assert res[1]["is_target"] is True
    assert res[1]["equipe"] == "EQ 2"
