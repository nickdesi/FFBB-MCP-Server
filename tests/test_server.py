"""Tests d'intégration pour le serveur MCP FFBB refactoré."""

import logging
import numbers

import pytest
from mcp.server.fastmcp import FastMCP

from ffbb_mcp.routes import (
    _build_index_html,
    _build_robots_txt,
    _build_sitemap_xml,
    _get_public_base_url,
)
from ffbb_mcp.server import (
    _resolve_log_level,
    _resolve_uvicorn_log_level,
    ffbb_version,
    mcp,
)


def test_server_initialization():
    """Vérifie que FastMCP est bien initialisé."""
    assert isinstance(mcp, FastMCP)
    assert mcp.name == "FFBB MCP Server"


@pytest.mark.asyncio
async def test_server_tools_importable():
    """Vérifie que les outils sont bien enregistrés via FastMCP."""
    tools = await mcp.list_tools()

    # Afin de tester de façon robuste et compatible FastMCP
    tool_names = [tool.name for tool in tools]

    expected = [
        "ffbb_version",
        "ffbb_search",
        "ffbb_bilan",
        "ffbb_team_summary",
        "ffbb_get",
        "ffbb_club",
        "ffbb_lives",
        "ffbb_saisons",
        "ffbb_resolve_team",
    ]

    for expected_name in expected:
        assert expected_name in tool_names, (
            f"L'outil '{expected_name}' est manquant dans l'enregistrement mcp."
        )


@pytest.mark.asyncio
async def test_ffbb_version_contract():
    """Vérifie le contrat de sortie de ffbb_version (dont cache_ttls)."""
    data = await ffbb_version()

    # Champs de base
    assert isinstance(data.get("package_version"), str) and data["package_version"], (
        "package_version doit être une chaîne non vide",
    )
    assert isinstance(data.get("python_version"), str) and data["python_version"], (
        "python_version doit être une chaîne non vide",
    )

    # cache_ttls doit être un dict avec des valeurs numériques
    cache_ttls = data.get("cache_ttls")
    assert isinstance(cache_ttls, dict), "cache_ttls doit être un dictionnaire"
    for key, value in cache_ttls.items():
        assert isinstance(value, numbers.Number), (
            f"cache_ttls['{key}'] doit être numérique (secondes)"
        )


@pytest.mark.asyncio
async def test_server_tool_signatures():
    """Vérifie que les outils ont des signatures aplaties."""
    tools = await mcp.list_tools()

    # Recherche d'un outil spécifique pour inspecter ses arguments
    tool = next(t for t in tools if t.name == "ffbb_get")

    # Dans FastMCP, les paramètres sont dans inputSchema
    props = tool.inputSchema.get("properties", {})
    assert "id" in props, "id devrait être un argument direct"
    assert "type" in props, "type devrait être un argument direct"

    # Vérifie que ffbb_search expose les nouveaux types sans nested params
    search_tool = next(t for t in tools if t.name == "ffbb_search")
    search_props = search_tool.inputSchema.get("properties", {})

    assert search_props.get("type", {}).get("type") == "string"
    assert set(search_props.get("type", {}).get("enum", [])) >= {
        "officiels",
        "entraineurs",
        "communes",
    }


def test_public_base_url_strips_mcp_suffix(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr/mcp/")

    assert _get_public_base_url() == "https://ffbb.desimone.fr"


def test_index_html_contains_seo_metadata(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr")

    html = _build_index_html()

    assert 'meta name="description"' in html
    assert 'rel="icon"' in html
    assert "FFBB MCP Server" in html


def test_robots_txt_contains_sitemap(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr/mcp")

    robots = _build_robots_txt()

    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert "Sitemap: https://ffbb.desimone.fr/sitemap.xml" in robots


def test_sitemap_xml_uses_canonical_root(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://ffbb.desimone.fr/mcp/")

    sitemap = _build_sitemap_xml()

    assert "<loc>https://ffbb.desimone.fr/</loc>" in sitemap
    assert "<changefreq>daily</changefreq>" in sitemap


def test_resolve_log_level_defaults_to_info():
    assert _resolve_log_level(None) == logging.INFO
    assert _resolve_log_level("unknown") == logging.INFO


def test_resolve_log_level_supports_common_values():
    assert _resolve_log_level("debug") == logging.DEBUG
    assert _resolve_log_level("warn") == logging.WARNING
    assert _resolve_log_level("error") == logging.ERROR


def test_resolve_uvicorn_log_level_mapping():
    assert _resolve_uvicorn_log_level(logging.DEBUG) == "debug"
    assert _resolve_uvicorn_log_level(logging.INFO) == "info"
    assert _resolve_uvicorn_log_level(logging.WARNING) == "warning"
    assert _resolve_uvicorn_log_level(logging.ERROR) == "error"
    assert _resolve_uvicorn_log_level(logging.CRITICAL) == "critical"


# -------------------------------------------------------------------
# Tests des outils MCP via le client FastMCP (couvre le corps server.py)
# (Ajoutés pour augmenter la couverture — alignés sur l'API réelle FastMCP 1.x)
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ffbb_lives_via_call_tool():
    """Couvre ffbb_lives (server.py ``ffbb_get_lives``) via ``mcp.call_tool``.

    En mode ``json_response=True``, FastMCP renvoie un tuple
    ``(content_list, structured_dict)`` (et non un ``CallToolResult``).
    """
    import json
    from unittest.mock import AsyncMock, patch

    fake_matches = [
        {"id": "rx1", "score_domicile": 42, "score_exterieur": 39},
    ]
    with patch(
        "ffbb_mcp.server.get_lives_service",
        new_callable=AsyncMock,
        return_value=fake_matches,
    ) as mock_svc:
        result = await mcp.call_tool("ffbb_lives", {})
        mock_svc.assert_called_once_with()
        # result = (content_list, structured_dict) en mode JSON.
        content_list, _structured = result
        assert content_list, "FastMCP doit renvoyer au moins un TextContent"
        payload = json.loads(content_list[0].text)
        # ``_freshness_meta`` peut envelopper la liste → on supporte dict ou list.
        items = payload if isinstance(payload, list) else [payload]
        first = items[0]
        assert first["id"] == "rx1"
        assert first["score_domicile"] == 42


@pytest.mark.asyncio
async def test_ffbb_get_competition_via_call_tool():
    """Couvre la branche ``type='competition'`` du switch dans ``ffbb_get``."""
    import json
    from unittest.mock import AsyncMock, patch

    fake_comp = {"id": 42, "nom": "Coupe du Puy-de-Dôme"}
    with patch(
        "ffbb_mcp.server.get_competition_service",
        new_callable=AsyncMock,
        return_value=fake_comp,
    ) as mock_svc:
        result = await mcp.call_tool("ffbb_get", {"id": 42, "type": "competition"})
        mock_svc.assert_called_once_with(competition_id=42)
        content_list, _structured = result
        assert content_list, "FastMCP doit renvoyer au moins un TextContent"
        payload = json.loads(content_list[0].text)
        # Le payload peut être soit l'objet direct, soit enveloppé sous "result".
        obj = payload.get("result", payload) if isinstance(payload, dict) else payload
        assert obj["nom"] == "Coupe du Puy-de-Dôme"


@pytest.mark.asyncio
async def test_ffbb_bilan_service_error_raises_tool_error():
    """Couvre la branche ``try/except`` de ``ffbb_bilan`` quand le service jette.

    Toute erreur du service est rattrapée par ``handle_api_error`` et
    remappée en ``ToolError`` ; côté serveur, ``_safe_report_progress``
    neutralise déjà l'appel hors requête réelle.
    """
    from unittest.mock import AsyncMock, patch

    from mcp.server.fastmcp.exceptions import ToolError

    expected_markers = (
        "Erreur API FFBB",
        "RuntimeError",
        "boom",
        "Action conseillée",
    )

    with patch(
        "ffbb_mcp.server.ffbb_bilan_service",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        try:
            await mcp.call_tool("ffbb_bilan", {"club_name": "ASVEL"})
        except ToolError as exc:
            # Format émis par handle_api_error() :
            # f"Erreur API FFBB ({error_type}): {error_msg}. Action conseillée: …"
            msg = str(exc)
            for marker in expected_markers:
                assert marker in msg, (
                    f"Marqueur manquant dans le message mappé : {marker!r}"
                )
        else:
            pytest.fail(
                "ToolError attendu : le service a jetté, mais aucune erreur n'a été levée"
            )


@pytest.mark.asyncio
async def test_ffbb_search_validation_error():
    """Couvre la branche ``except ValueError`` de ``ffbb_search`` (filter_by invalide).

    On ancre sur le substring littéral émis par ``_validate_filter_by()``.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError) as exc_info:
        await mcp.call_tool(
            "ffbb_search",
            {"query": "test", "filter_by": "bad\x00input"},
        )
    msg = str(exc_info.value)
    assert "caractères de contrôle invalides" in msg


@pytest.mark.asyncio
async def test_safe_report_progress_swallows_value_error():
    """Verrouille le contrat de capture (ValueError, AssertionError) du helper.

    Quand FastMCP expose un ``Context`` hors d'un vrai RequestContext (cas des
    tests unitaires ``mcp.call_tool``), ``ctx.report_progress`` lève
    ``ValueError("Context is not available outside of a request")``. Le helper
    doit swallow + logger en DEBUG sans propager.
    """
    from unittest.mock import AsyncMock, MagicMock

    from ffbb_mcp.server import _safe_report_progress

    ctx = MagicMock()
    ctx.report_progress = AsyncMock(
        side_effect=ValueError("Context is not available outside of a request"),
    )

    result = await _safe_report_progress(ctx, 0.0, total=3, message="start")
    assert result is None
    ctx.report_progress.assert_awaited_once_with(0.0, total=3, message="start")


@pytest.mark.asyncio
async def test_safe_report_progress_passes_through_runtime_error():
    """Verrouille la promesse inverse : seule ``(ValueError, AssertionError)`` est swallowée.

    Toute autre exception applicative (ici ``RuntimeError``) doit remonter pour
    ne pas masquer un bug réel dans le code appelant.
    """
    from unittest.mock import AsyncMock, MagicMock

    from ffbb_mcp.server import _safe_report_progress

    ctx = MagicMock()
    ctx.report_progress = AsyncMock(side_effect=RuntimeError("oops"))

    with pytest.raises(RuntimeError, match="oops"):
        await _safe_report_progress(ctx, 1.0, total=2, message="middle")


def test_allowed_origins_default_to_wildcard(monkeypatch):
    """Vérifie que _allowed_origins est par défaut sur '*' pour autoriser les clients IA distants (Perplexity, ChatGPT, etc.)."""
    import ffbb_mcp.server as server_mod

    assert "*" in server_mod._allowed_origins


@pytest.mark.asyncio
async def test_team_summary_resolves_team_with_numero_equipe():
    """Vérifie que ffbb_team_summary passe effective_cat et numero_equipe à ffbb_resolve_team_service."""
    from unittest.mock import AsyncMock, patch

    from ffbb_mcp.server import ffbb_team_summary

    mock_resolve = AsyncMock(
        return_value={
            "status": "resolved",
            "team": {
                "team_id": 1001,
                "team_label": "SEM1",
                "numero_equipe": "1",
                "nom_equipe": "STADE CLERMONTOIS",
                "competition": "Pré nationale masculine",
            },
            "club_resolu": {"organisme_id": 9326, "nom": "STADE CLERMONTOIS"},
        }
    )
    mock_bilan = AsyncMock(
        return_value={
            "bilan_total": {"match_joues": 0, "gagnes": 0, "perdus": 0},
            "phase_courante": {"competition": "Pré nationale masculine"},
        }
    )
    mock_last = AsyncMock(return_value=None)
    mock_next = AsyncMock(
        return_value={
            "status": "ok",
            "team": {"team_id": 1001, "team_label": "SEM1"},
            "match": {"adversaire": "OUEST LYONNAIS BASKET"},
        }
    )

    with (
        patch("ffbb_mcp.server.ffbb_resolve_team_service", mock_resolve),
        patch("ffbb_mcp.server.ffbb_bilan_service", mock_bilan),
        patch("ffbb_mcp.server.ffbb_last_result_service", mock_last),
        patch("ffbb_mcp.server.ffbb_next_match_service", mock_next),
    ):
        res = await ffbb_team_summary(
            organisme_id=9326,
            categorie="SEM",
            numero_equipe=1,
        )

        mock_resolve.assert_awaited_once_with(
            club_name=None,
            organisme_id=9326,
            categorie="SEM1",
            numero_equipe=1,
        )
        assert res["team"] is not None
        assert res["team"]["team_label"] == "SEM1"
        assert res["phase_courante"] == {"competition": "Pré nationale masculine"}
        assert res["next_match"] is not None
