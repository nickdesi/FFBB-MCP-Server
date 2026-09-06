from __future__ import annotations

# Note mypy: les annotations `# type: ignore[untyped-decorator]` du fichier
# (sur `@mcp.custom_route(...)`) proviennent uniquement du décorateur
# FastMCP `mcp.custom_route` dont les stubs officiels ne sont pas typés.
# Pas de fond à corriger côté projet — la convention est documentée ici.
import asyncio
import contextlib
import datetime
import logging
import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from starlette.requests import Request

from starlette.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from . import __version__ as _PACKAGE_VERSION
from ._state import _read_positive_int_env
from .dashboard import _build_dashboard_html
from .metrics import generate_prometheus_metrics, get_snapshot, summarize_health
from .utils import OrjsonResponse

_DEFAULT_PUBLIC_URL = "https://ffbb.desimone.fr"
_REMOTE_LOGO_URL = (
    "https://raw.githubusercontent.com/nickdesi/FFBB-MCP-Server/main/assets/logo.webp"
)
logger = logging.getLogger("ffbb-mcp")
_background_tasks: set[asyncio.Task] = set()

# Bornes de sécurité de l'endpoint /cache/warmup (CWE-400 : DoS par ressources).
_WARMUP_MAX_ORGANISMES = _read_positive_int_env("FFBB_WARMUP_MAX_ORGANISMES", 50)
_WARMUP_MAX_BODY_BYTES = 64 * 1024


def _find_website_dir() -> Path:
    # Détecte le dossier website/ en local ou en production
    repo_path = Path(__file__).resolve().parents[2] / "website"
    if repo_path.exists():
        return repo_path
    pkg_path = Path(__file__).resolve().parent / "website"
    if pkg_path.exists():
        return pkg_path
    prod_path = Path("/app/website")
    if prod_path.exists():
        return prod_path
    return Path.cwd() / "website"


_WEBSITE_DIR = _find_website_dir()
_LOGO_PATH = _WEBSITE_DIR / "logo.webp"


def _get_public_base_url() -> str:
    public_url = os.environ.get("PUBLIC_URL", _DEFAULT_PUBLIC_URL).strip()
    if not public_url:
        return _DEFAULT_PUBLIC_URL
    normalized = public_url.rstrip("/")
    if normalized.endswith("/mcp"):
        normalized = normalized[: -len("/mcp")]
    return normalized or _DEFAULT_PUBLIC_URL


def _get_logo_url() -> str:
    return f"{_get_public_base_url()}/logo.webp"


def _build_index_html() -> str:
    index_path = _WEBSITE_DIR / "index.html"
    if index_path.exists():
        try:
            return index_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read index.html: {e}")
    return (
        "<html><body><h1>FFBB MCP Server</h1><p>Site en maintenance.</p></body></html>"
    )


def _build_robots_txt() -> str:
    base_url = _get_public_base_url()
    return f"""User-agent: *
Allow: /
Allow: /docs/

Sitemap: {base_url}/sitemap.xml

# AI Search & GEO Discovery (Perplexity, Gemini, ChatGPT, Claude)
User-agent: PerplexityBot
Allow: /

User-agent: Perplexity-User
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: GoogleOther
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: Claude-Web
Allow: /

# Aggressive Model-Training Scrapers
User-agent: Bytespider
Disallow: /

User-agent: CCBot
Disallow: /
"""


def _build_sitemap_xml() -> str:
    canonical_url = f"{_get_public_base_url()}/"
    lastmod = datetime.date.today().isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{canonical_url}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""


def _logo_response() -> Response:
    if _LOGO_PATH.exists():
        return FileResponse(_LOGO_PATH, media_type="image/webp")
    return RedirectResponse(_REMOTE_LOGO_URL)


def register_routes(mcp: FastMCP) -> None:
    """Registers all custom HTTP routes on the FastMCP instance."""

    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
    async def health(_request: Request) -> Response:
        """Endpoint de santé enrichi — lisible par machine et humain."""
        snap = get_snapshot()
        summary = summarize_health(snap)
        uptime_s = snap["uptime_seconds"]
        days = int(uptime_s // 86400)
        hours = int((uptime_s % 86400) // 3600)
        minutes = int((uptime_s % 3600) // 60)
        seconds = int(uptime_s % 60)
        return OrjsonResponse(
            {
                "status": summary["status"],
                "service": "ffbb-mcp",
                "version": _PACKAGE_VERSION,
                "transport": "streamable-http",
                "spec": "2025-11-25",
                "uptime_seconds": round(uptime_s, 1),
                "uptime_human": f"{days}j {hours:02d}:{minutes:02d}:{seconds:02d}",
                "api_calls_total": summary["api_calls_total"],
                "api_calls_success": summary["api_calls_success"],
                "api_errors_total": summary["api_errors_total"],
                "api_error_rate": round(summary["api_error_rate"], 4),
                "api_avg_latency_ms": round(
                    summary["api_avg_latency_seconds"] * 1000, 2
                ),
                "api_inflight_requests": summary["api_inflight_requests"],
                "cache_hits_total": summary["cache_hits_total"],
                "cache_misses_total": summary["cache_misses_total"],
                "cache_hit_ratio_global": round(summary["cache_hit_ratio_global"], 4),
                "timestamp": datetime.datetime.now(datetime.UTC)
                .replace(tzinfo=None)
                .isoformat()
                + "Z",
                "python_version": platform.python_version(),
                "public_url": _get_public_base_url(),
            }
        )

    @mcp.custom_route("/metrics", methods=["GET"])  # type: ignore[untyped-decorator]
    async def metrics(_request: Request) -> Response:
        return PlainTextResponse(generate_prometheus_metrics())

    @mcp.custom_route("/metrics.json", methods=["GET"])  # type: ignore[untyped-decorator]
    async def metrics_json(_request: Request) -> Response:
        """Snapshot des métriques au format JSON (pour le dashboard front-end)."""
        snap = get_snapshot()
        if "cache_miss_reasons" in snap:
            snap["cache_miss_reasons"] = {
                f"{cache}:{reason}": count
                for (cache, reason), count in snap["cache_miss_reasons"].items()
            }
        return OrjsonResponse(
            {
                "service": "ffbb-mcp",
                "version": _PACKAGE_VERSION,
                "timestamp": datetime.datetime.now(datetime.UTC)
                .replace(tzinfo=None)
                .isoformat()
                + "Z",
                **snap,
            }
        )

    @mcp.custom_route("/dashboard", methods=["GET"])  # type: ignore[untyped-decorator]
    async def dashboard(_request: Request) -> Response:
        """Dashboard de supervision HTML — lisible humain, demo-friendly."""
        return HTMLResponse(content=_build_dashboard_html(), status_code=200)

    @mcp.custom_route("/docs", methods=["GET"])  # type: ignore[untyped-decorator]
    async def docs(_request: Request) -> Response:
        return RedirectResponse("/docs/")

    @mcp.custom_route("/docs/", methods=["GET"])  # type: ignore[untyped-decorator]
    async def docs_slash(_request: Request) -> Response:
        local_doc = _WEBSITE_DIR / "docs" / "index.html"
        if local_doc.exists():
            return HTMLResponse(
                content=local_doc.read_text(encoding="utf-8"), status_code=200
            )
        return RedirectResponse(
            "https://github.com/nickdesi/FFBB-MCP-Server/tree/main/docs"
        )

    @mcp.custom_route("/docs/{path:path}", methods=["GET"])  # type: ignore[untyped-decorator]
    async def docs_wildcard(request: Request) -> Response:
        path = request.path_params.get("path", "")
        docs_root = (_WEBSITE_DIR / "docs").resolve()
        try:
            local_doc = (docs_root / path).resolve()
            if docs_root not in local_doc.parents and local_doc != docs_root:
                return Response("Forbidden", status_code=403)
        except Exception:
            return Response("Not Found", status_code=404)
        if local_doc.exists() and local_doc.is_file():
            if local_doc.suffix == ".html":
                return HTMLResponse(
                    content=local_doc.read_text(encoding="utf-8"), status_code=200
                )
            return FileResponse(local_doc)
        return RedirectResponse(
            f"https://github.com/nickdesi/FFBB-MCP-Server/blob/main/docs/{path}"
        )

    @mcp.custom_route("/logo.webp", methods=["GET"])  # type: ignore[untyped-decorator]
    async def logo(_request: Request) -> Response:
        return _logo_response()

    @mcp.custom_route("/favicon.ico", methods=["GET"])  # type: ignore[untyped-decorator]
    async def favicon(_request: Request) -> Response:
        return _logo_response()

    @mcp.custom_route("/css/style.css", methods=["GET"])  # type: ignore[untyped-decorator]
    async def style_css(_request: Request) -> Response:
        css_path = _WEBSITE_DIR / "css" / "style.css"
        if css_path.exists():
            return FileResponse(css_path, media_type="text/css")
        return Response("/* CSS non trouvé */", status_code=404)

    @mcp.custom_route("/llms.txt", methods=["GET"])  # type: ignore[untyped-decorator]
    async def llms_txt(_request: Request) -> Response:
        llms_path = _WEBSITE_DIR / "llms.txt"
        if llms_path.exists():
            return PlainTextResponse(llms_path.read_text(encoding="utf-8"))
        return Response("Not Found", status_code=404)

    @mcp.custom_route("/llms-full.txt", methods=["GET"])  # type: ignore[untyped-decorator]
    async def llms_full_txt(_request: Request) -> Response:
        llms_path = _WEBSITE_DIR / "llms-full.txt"
        if llms_path.exists():
            return PlainTextResponse(llms_path.read_text(encoding="utf-8"))
        return Response("Not Found", status_code=404)

    @mcp.custom_route("/robots.txt", methods=["GET"])  # type: ignore[untyped-decorator]
    async def robots_txt(_request: Request) -> Response:
        return PlainTextResponse(_build_robots_txt())

    @mcp.custom_route("/sitemap.xml", methods=["GET"])  # type: ignore[untyped-decorator]
    async def sitemap_xml(_request: Request) -> Response:
        return Response(_build_sitemap_xml(), media_type="application/xml")

    @mcp.custom_route("/cache/warmup", methods=["POST"])  # type: ignore[untyped-decorator]
    async def cache_warmup_post(request: Request) -> Response:
        """Déclenche le préchauffage du cache."""
        # Authentification optionnelle : si FFBB_WARMUP_API_KEY est définie,
        # elle est obligatoire (Authorization: Bearer <clé>).
        api_key = os.environ.get("FFBB_WARMUP_API_KEY", "")
        if api_key:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {api_key}":
                return OrjsonResponse(
                    {"error": "Unauthorized", "error_type": "InvalidApiKey"},
                    status_code=401,
                )

        # Borne la taille du body pour éviter les DoS mémoire (CWE-400).
        content_length = request.headers.get("Content-Length")
        try:
            too_large = int(content_length or "0") > _WARMUP_MAX_BODY_BYTES
        except TypeError, ValueError:
            too_large = False
        if too_large:
            return OrjsonResponse(
                {
                    "error": "Payload Too Large",
                    "error_type": "BodyTooLarge",
                    "max_bytes": _WARMUP_MAX_BODY_BYTES,
                },
                status_code=413,
            )

        try:
            body = await request.json()
        except Exception:
            body = {}

        organisme_ids = body.get("organisme_ids") if isinstance(body, dict) else None
        sync_mode = body.get("sync", False) if isinstance(body, dict) else False

        # Validation stricte de la liste : type + taille bornée (CWE-400).
        if organisme_ids is not None:
            if not isinstance(organisme_ids, list) or not all(
                isinstance(oid, str) and oid.strip() for oid in organisme_ids
            ):
                return OrjsonResponse(
                    {
                        "error": "Bad Request",
                        "error_type": "InvalidOrganismeIds",
                        "message": "'organisme_ids' doit être une liste de chaînes non vides.",
                    },
                    status_code=400,
                )
            if len(organisme_ids) > _WARMUP_MAX_ORGANISMES:
                return OrjsonResponse(
                    {
                        "error": "Payload Too Large",
                        "error_type": "TooManyOrganismeIds",
                        "max_organismes": _WARMUP_MAX_ORGANISMES,
                    },
                    status_code=413,
                )

        if sync_mode:
            from .services.warmup import warmup_cache_service

            res = await warmup_cache_service(organisme_ids=organisme_ids)
            return OrjsonResponse(res, status_code=200)
        else:
            from .services.warmup import warmup_cache_service

            task = asyncio.create_task(
                warmup_cache_service(organisme_ids=organisme_ids)
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            return OrjsonResponse(
                {
                    "status": "accepted",
                    "message": "Le préchauffage du cache a été déclenché en tâche de fond.",
                },
                status_code=202,
            )

    @mcp.custom_route("/api/scba/matches", methods=["GET"])  # type: ignore[untyped-decorator]
    @mcp.custom_route("/api/v1/club/{organisme_id}/matches", methods=["GET"])  # type: ignore[untyped-decorator]
    async def club_matches_api(request: Request) -> Response:
        """Retourne l'ensemble des rencontres d'un club pour les applications web (ex: SCBA-Benevolat)."""
        organisme_id_raw = request.path_params.get("organisme_id", "9326")
        try:
            organisme_id = int(organisme_id_raw)
        except ValueError, TypeError:
            organisme_id = 9326

        team_filter = request.query_params.get("team")

        from .client import get_client_async

        client = await get_client_async()

        try:
            org = await client.get_organisme_async(organisme_id=organisme_id)
            if not org:
                return OrjsonResponse(
                    {"error": "Club introuvable", "matches": [], "count": 0},
                    status_code=404,
                    headers={"Access-Control-Allow-Origin": "*"},
                )
        except Exception as e:
            return OrjsonResponse(
                {"error": str(e), "matches": [], "count": 0},
                status_code=500,
                headers={"Access-Control-Allow-Origin": "*"},
            )

        club_name = getattr(org, "nom", "") or "Club"
        club_logo_url: str | None = None
        if getattr(org, "logo", None):
            logo_id = getattr(org.logo, "id", None) or org.logo
            if logo_id:
                club_logo_url = f"https://api.ffbb.com/assets/{logo_id}"

        engagements = getattr(org, "engagements", []) or []
        matches_list: list[dict[str, Any]] = []
        seen_match_ids: set[str] = set()

        WEEKDAYS_FR = [
            "Lundi",
            "Mardi",
            "Mercredi",
            "Jeudi",
            "Vendredi",
            "Samedi",
            "Dimanche",
        ]
        MONTHS_FR = [
            "Janvier",
            "Février",
            "Mars",
            "Avril",
            "Mai",
            "Juin",
            "Juillet",
            "Août",
            "Septembre",
            "Octobre",
            "Novembre",
            "Décembre",
        ]

        def _fmt_date(iso_str: str) -> str:
            if not iso_str:
                return ""
            try:
                parts = iso_str.split("-")
                if len(parts) != 3:
                    return iso_str
                dt = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
                return f"{WEEKDAYS_FR[dt.weekday()]} {dt.day} {MONTHS_FR[dt.month - 1]} {dt.year}"
            except Exception:
                return iso_str

        def _clean_opp(raw: str) -> str:
            if not raw:
                return "Adversaire Inconnu"
            import re

            return re.sub(
                r"^(IE\s*[-]?\s*|CTC\s*[-]?\s*)", "", raw.strip(), flags=re.IGNORECASE
            ).strip()

        def _norm_team(team_raw: str, comp_name: str = "") -> str:
            import re

            raw = (team_raw or "").upper().strip()
            comp = (comp_name or "").upper().strip()

            if "BABY" in raw or "BABY" in comp:
                return "U7 M1"
            if "MINI" in raw or "MINI" in comp:
                return "U9 M1"

            m_cat = re.search(r"U\s*(\d+)", raw) or re.search(r"U\s*(\d+)", comp)
            if m_cat:
                cat = m_cat.group(1)
                m_num = re.search(r"[- ](\d+)$", raw)
                num = m_num.group(1) if m_num else "1"
                return f"U{cat} M{num}"
            m_num = re.search(r"[- ](\d+)$", raw)
            num = m_num.group(1) if m_num else None
            if not num:
                if "RM2" in comp or "DIVISION 2" in comp:
                    num = "2"
                elif (
                    "RM3" in comp
                    or "DIVISION 3" in comp
                    or "DM2" in comp
                    or "DM3" in comp
                    or "PRM" in comp
                ):
                    num = "3"
                elif (
                    "PNM" in comp or "PRE NATIONALE" in comp or "PRÉ NATIONALE" in comp
                ):
                    num = "1"
                else:
                    num = "1"
            return f"SENIOR M{num}"

        for eng in engagements:
            poule_obj = getattr(eng, "idPoule", None)
            comp_obj = getattr(eng, "idCompetition", None)
            poule_id = getattr(poule_obj, "id", None) or (
                str(poule_obj) if poule_obj else None
            )
            comp_nom = getattr(comp_obj, "nom", "") or ""

            if not poule_id:
                continue

            try:
                poule = await client.get_poule_async(poule_id=int(poule_id))
                rencontres = getattr(poule, "rencontres", []) or []
            except Exception:
                continue

            for m in rencontres:
                m_id = str(getattr(m, "id", "") or "")
                if not m_id or m_id in seen_match_ids:
                    continue

                nom_eq1 = getattr(m, "nomEquipe1", "") or ""
                nom_eq2 = getattr(m, "nomEquipe2", "") or ""
                id_org1 = str(getattr(m, "idOrganismeEquipe1", "") or "")
                id_org2 = str(getattr(m, "idOrganismeEquipe2", "") or "")

                is_club1 = (
                    id_org1 == str(organisme_id) or club_name.upper() in nom_eq1.upper()
                )
                is_club2 = (
                    id_org2 == str(organisme_id) or club_name.upper() in nom_eq2.upper()
                )

                if not is_club1 and not is_club2:
                    continue

                seen_match_ids.add(m_id)
                is_home = is_club1
                local_team_raw = nom_eq1 if is_home else nom_eq2
                opp_team_raw = nom_eq2 if is_home else nom_eq1
                opp_org_id = id_org2 if is_home else id_org1

                team_name = _norm_team(local_team_raw, comp_nom)
                opponent = _clean_opp(opp_team_raw)

                if (
                    team_filter
                    and team_filter != "ALL"
                    and team_filter.upper() not in team_name.upper()
                ):
                    continue

                date_raw = str(
                    getattr(m, "date_rencontre", "") or getattr(m, "date", "") or ""
                )
                date_iso = date_raw[:10] if date_raw.startswith("20") else ""

                import re

                time_str = "15:00"
                horaire = str(getattr(m, "horaire", "") or "")
                if horaire:
                    h_clean = re.sub(r"[hH:]", "", horaire).strip()
                    if len(h_clean) == 4:
                        time_str = f"{h_clean[:2]}:{h_clean[2:]}"
                    elif len(h_clean) == 2:
                        time_str = f"{h_clean}:00"
                elif " " in date_raw:
                    time_part = date_raw.split(" ")[1][:5]
                    if ":" in time_part:
                        time_str = time_part

                match_data = {
                    "ffbbMatchId": m_id,
                    "team": team_name,
                    "opponent": opponent,
                    "date": _fmt_date(date_iso),
                    "dateISO": date_iso,
                    "time": time_str,
                    "location": f"Domicile ({club_name})"
                    if is_home
                    else f"Extérieur ({opponent})",
                    "isHome": is_home,
                    "competition": comp_nom,
                    "teamLogo": club_logo_url,
                    "salle": getattr(m, "salle", None),
                    "opp_org_id": opp_org_id,
                }
                matches_list.append(match_data)

        # Enrichissement en batch des adresses de gymnases
        from .services.salle import _enrich_matches_with_salle_details

        await _enrich_matches_with_salle_details(matches_list)

        # Enrichissement des logos adverses
        opp_org_ids = [
            str(oid)
            for m in matches_list
            if (oid := m.get("opp_org_id")) is not None and str(oid).strip()
        ]
        opp_org_ids = list(dict.fromkeys(opp_org_ids))
        logo_map: dict[str, str] = {}
        if opp_org_ids:

            async def _fetch_logo(org_id: str) -> tuple[str, str | None]:
                try:
                    org_data = await client.get_organisme_async(
                        organisme_id=int(org_id)
                    )
                    if org_data and getattr(org_data, "logo", None):
                        logo_id = getattr(org_data.logo, "id", None) or org_data.logo
                        if logo_id:
                            return org_id, f"https://api.ffbb.com/assets/{logo_id}"
                except Exception:
                    pass
                return org_id, None

            logo_results = await asyncio.gather(
                *[_fetch_logo(oid) for oid in opp_org_ids], return_exceptions=True
            )
            for res in logo_results:
                if isinstance(res, tuple) and res[1]:
                    logo_map[res[0]] = res[1]

        for m in matches_list:
            opp_id = m.pop("opp_org_id", None)
            if opp_id and opp_id in logo_map:
                m["opponentLogo"] = logo_map[opp_id]
            is_h = m.get("isHome", False)
            if m.get("adresse_salle"):
                m["location"] = m["adresse_salle"]
            elif is_h:
                m["location"] = f"Domicile ({club_name})"
            else:
                m["location"] = f"Extérieur ({m.get('opponent', 'Adversaire')})"
            m.pop("salle", None)
            m.pop("salle_details", None)
            m.pop("adresse_salle", None)

        matches_list.sort(key=lambda x: (x.get("dateISO", ""), x.get("time", "")))

        return OrjsonResponse(
            {
                "organisme_id": organisme_id,
                "club": club_name,
                "matches": matches_list,
                "count": len(matches_list),
            },
            headers={"Access-Control-Allow-Origin": "*"},
        )

    @mcp.custom_route("/api/v1/next-match", methods=["GET"])  # type: ignore[untyped-decorator]
    @mcp.custom_route("/api/v1/club/{organisme_id}/next-match", methods=["GET"])  # type: ignore[untyped-decorator]
    async def next_match_api(request: Request) -> Response:
        """Retourne le prochain match d'un club/équipe pour Home Assistant ou les widgets."""
        organisme_id_raw = request.path_params.get(
            "organisme_id"
        ) or request.query_params.get("organisme_id")
        club_name = request.query_params.get("club_name")
        categorie = (
            request.query_params.get("categorie")
            or request.query_params.get("category")
            or "SEM1"
        )
        num_eq_raw = request.query_params.get(
            "numero_equipe"
        ) or request.query_params.get("num")
        force_refresh = request.query_params.get("force_refresh", "").lower() in (
            "1",
            "true",
            "yes",
        )

        organisme_id: int | str | None = None
        if organisme_id_raw:
            try:
                organisme_id = int(organisme_id_raw)
            except ValueError:
                organisme_id = str(organisme_id_raw)

        numero_equipe: int = 1
        if num_eq_raw:
            with contextlib.suppress(ValueError):
                numero_equipe = int(num_eq_raw)

        from .services.club import ffbb_next_match_service

        try:
            res = await ffbb_next_match_service(
                categorie=categorie,
                club_name=club_name,
                organisme_id=organisme_id,
                numero_equipe=numero_equipe,
                force_refresh=force_refresh,
            )
            return OrjsonResponse(res, headers={"Access-Control-Allow-Origin": "*"})
        except Exception as e:
            return OrjsonResponse(
                {"status": "error", "error": str(e)},
                status_code=500,
                headers={"Access-Control-Allow-Origin": "*"},
            )

    @mcp.custom_route("/cache/warmup", methods=["GET"])  # type: ignore[untyped-decorator]
    async def cache_warmup_get(_request: Request) -> Response:
        """Informations sur l'endpoint de préchauffage du cache."""
        return OrjsonResponse(
            {
                "endpoint": "/cache/warmup",
                "methods": ["POST", "GET"],
                "description": "Préchauffe proactivement le cache FFBB pour les clubs favoris.",
                "usage_post": "POST {'organisme_ids': ['123', '456'], 'sync': false}",
                "env_var_config": "FFBB_WARMUP_ORGANISMES",
                "limits": {
                    "max_organisme_ids": _WARMUP_MAX_ORGANISMES,
                    "max_body_bytes": _WARMUP_MAX_BODY_BYTES,
                },
                "auth": (
                    "Requires Authorization: Bearer <FFBB_WARMUP_API_KEY>"
                    if os.environ.get("FFBB_WARMUP_API_KEY")
                    else "Open (no FFBB_WARMUP_API_KEY configured); set it to require a bearer token"
                ),
            }
        )

    @mcp.custom_route("/", methods=["GET"])  # type: ignore[untyped-decorator]
    async def index(_request: Request) -> Response:
        return HTMLResponse(content=_build_index_html(), status_code=200)
