"""Dashboard HTML pour le serveur FFBB MCP — route /dashboard."""

import datetime
import math

from . import __version__ as _PACKAGE_VERSION
from .benchmark import get_benchmark_trends
from .metrics import get_snapshot

_CORE_TOOLS = {
    "ffbb_search",
    "ffbb_resolve_team",
    "ffbb_next_match",
    "ffbb_last_result",
    "ffbb_club",
    "ffbb_get",
}


def _build_benchmark_html() -> str:
    trends = get_benchmark_trends()
    latest = trends["latest"]

    if not latest:
        return (
            "<div class='section-title'>&#9889; Benchmark Performance</div>"
            "<div class='kpi'><p class='label'>Aucun benchmark lancé. "
            "Utilisez <code>/benchmark</code> ou lancez depuis GitHub Actions.</p></div>"
        )

    direction_icon = {
        "improving": "&#9650;",
        "degrading": "&#9660;",
        "stable": "&#9654;",
        "unknown": "&#9679;",
    }
    direction_label = {
        "improving": "Amélioration",
        "degrading": "Dégradation",
        "stable": "Stable",
        "unknown": "Inconnue",
    }
    dir_icon = direction_icon.get(trends["direction"], "&#9679;")
    dir_label = direction_label.get(trends["direction"], "")

    runs = trends["runs"]
    max_in_chart = min(trends["total_runs"], 20)
    chart_bars = ""
    if runs and trends["average_ms"]:
        max_val = max(r["total_ms"] for r in runs[-max_in_chart:]) or 1
        for r in runs[-max_in_chart:]:
            pct = (r["total_ms"] / max_val) * 100
            color = "#00e676" if r["success"] else "#ff5252"
            bar = (
                f"<div class='bench-bar-wrap' title='{r.get('timestamp', '')[:19]} "
                f"— {'OK' if r['success'] else 'ECHEC'}: {r['total_ms']}ms'>"
                f"<div class='bench-bar' style='height:{pct:.0f}%;background:{color}'></div>"
                f"</div>"
            )
            chart_bars += bar

    latest_ms = latest["total_ms"]
    avg_ms = trends["average_ms"]
    success_rate = trends["success_rate"]
    trend_dir = f"{dir_icon} {dir_label}"

    step_rows = ""
    for s in latest.get("steps", []):
        step_rows += (
            f"<tr>"
            f"<td class='cache-name'>{s['name']}</td>"
            f"<td class='num'>{s['duration_ms']}ms</td>"
            f"</tr>"
        )

    html = (
        "<div class='section-title'>&#9889; Benchmark Performance</div>"
        "<div class='kpi-grid'>"
        f"<div class='kpi'><div class='label'>Dernier run</div>"
        f"<div class='value'>{latest_ms}<span style='font-size:14px;color:var(--muted)'>ms</span></div>"
        f"<div class='sub'>{latest.get('scenario', '')}</div></div>"
        f"<div class='kpi'><div class='label'>Moyenne</div>"
        f"<div class='value accent'>{avg_ms or '—'}<span style='font-size:14px;color:var(--muted)'>ms</span></div>"
        f"<div class='sub'>sur {trends['total_runs']} runs</div></div>"
        f"<div class='kpi'><div class='label'>Succès</div>"
        f"<div class='value green'>{success_rate}%</div>"
        f"<div class='sub'></div></div>"
        f"<div class='kpi'><div class='label'>Tendance</div>"
        f"<div class='value' style='font-size:20px'>{trend_dir}</div>"
        f"<div class='sub'>3 derniers runs</div></div>"
        "</div>"
        "<div class='section-title' style='margin-top:16px'>&#128200; Latence (derniers runs)</div>"
        f"<div class='bench-chart'>{chart_bars}</div>"
        "<div class='table-container' style='margin-top:16px'>"
        "<table>"
        "<thead><tr><th>Étape</th><th style='text-align:right'>Durée</th></tr></thead>"
        f"<tbody>{step_rows}</tbody>"
        "</table>"
        "</div>"
    )
    return html


def _build_dashboard_html() -> str:
    snap = get_snapshot()
    now_utc = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    uptime_s = snap["uptime_seconds"]
    days = int(uptime_s // 86400)
    hours = int((uptime_s % 86400) // 3600)
    minutes = int((uptime_s % 3600) // 60)
    seconds = int(uptime_s % 60)
    uptime_fmt = f"{days}j {hours:02d}:{minutes:02d}:{seconds:02d}"

    calls = snap["api_calls_success"] + snap["api_calls_error"]
    errors = snap["api_calls_error"]
    error_rate = snap["api_error_rate"]
    avg_lat_ms = snap["api_avg_latency_seconds"] * 1000
    inflight = snap["api_inflight_requests"]
    cache_stats = snap.get("cache", {})
    tool_calls = snap.get("tool_calls", {})
    hits = sum(s["hits"] for s in cache_stats.values())
    misses = sum(s["misses"] for s in cache_stats.values())
    cache_total = hits + misses
    hit_ratio = hits / cache_total if cache_total else 0.0
    core_calls = sum(count for name, count in tool_calls.items() if name in _CORE_TOOLS)
    legacy_calls = sum(
        count for name, count in tool_calls.items() if name not in _CORE_TOOLS
    )

    tool_rows = ""
    for name, count in sorted(tool_calls.items(), key=lambda item: (-item[1], item[0])):
        bucket = "CORE" if name in _CORE_TOOLS else "LEGACY"
        tool_rows += (
            f"<tr>"
            f"<td class='cache-name'>{name}</td>"
            f"<td class='num'>{count}</td>"
            f"<td>{bucket}</td>"
            f"</tr>"
        )

    if not tool_rows:
        tool_rows = (
            "<tr><td colspan='3' class='empty'>Aucun appel outil MCP observe.</td></tr>"
        )

    status_badge_cls = "healthy" if error_rate <= 0.05 else "degraded"
    status_label = "HEALTHY" if error_rate <= 0.05 else "DEGRADED"

    benchmark_html = _build_benchmark_html()

    RING_R = 52
    ring_c = 2 * math.pi * RING_R
    ring_offset = ring_c * (1 - hit_ratio)

    cache_rows = ""
    for name, stat in cache_stats.items():
        ratio_pct = stat["hit_ratio"] * 100
        bar_color = (
            "#00e676"
            if ratio_pct >= 80
            else ("#ffab40" if ratio_pct >= 50 else "#ff5252")
        )
        cache_rows += (
            f"<tr>"
            f"<td class='cache-name'>{name}</td>"
            f"<td class='num'>{stat['hits']}</td>"
            f"<td class='num'>{stat['misses']}</td>"
            f"<td class='num'>{stat['total']}</td>"
            f"<td><div class='bar-track'><div class='bar-fill' style='width:{ratio_pct:.1f}%;background:{bar_color}'></div></div>"
            f"<span class='bar-label'>{ratio_pct:.1f}%</span></td>"
            f"</tr>"
        )

    if not cache_rows:
        cache_rows = "<tr><td colspan='5' class='empty'>Aucune donnee de cache — aucun appel API effectue.</td></tr>"

    hit_pct = hit_ratio * 100
    inflight_class = "accent" if inflight > 0 else ""
    error_class = "red" if errors > 0 else "green"

    html = (
        "<!DOCTYPE html>\n"
        "<html lang='fr'>\n"
        "<head>\n"
        "  <meta charset='UTF-8' />\n"
        "  <meta name='viewport' content='width=device-width, initial-scale=1.0' />\n"
        "  <title>FFBB MCP Dashboard</title>\n"
        "  <link rel='preconnect' href='https://fonts.googleapis.com'>\n"
        "  <link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>\n"
        "  <link href='https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Space+Grotesk:wght@400;500;700&display=swap' rel='stylesheet'>\n"
        "  <style>\n"
        "    :root{--bg:#05060a;--surface:rgba(255,255,255,0.04);--surface2:rgba(255,255,255,0.07);--border:rgba(255,255,255,0.09);--accent:#ff5722;--accent2:#ff2d95;--cyan:#22d3ee;--violet:#a855f7;--green:#00e676;--red:#ff5252;--yellow:#ffab40;--text:#eef1f7;--muted:#7e879c;--grad:linear-gradient(135deg,#ff5722,#ff2d95 45%,#22d3ee);--mono:'Space Grotesk','Inter','Segoe UI',system-ui,sans-serif;--display:'Orbitron','Space Grotesk',sans-serif}\n"
        "    *{box-sizing:border-box;margin:0;padding:0}\n"
        "    html{scroll-behavior:smooth}\n"
        "    body{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:14px;line-height:1.55;min-height:100vh;overflow-x:hidden}\n"
        "    .bg{position:fixed;inset:0;z-index:-2;overflow:hidden;background:radial-gradient(1200px 600px at 80% -10%,rgba(255,45,149,.12),transparent 60%),radial-gradient(900px 500px at -10% 110%,rgba(34,211,238,.12),transparent 60%),var(--bg)}\n"
        "    .orb{position:absolute;border-radius:50%;filter:blur(90px);opacity:.45;mix-blend-mode:screen}\n"
        "    .o1{width:460px;height:460px;background:var(--accent);top:-120px;right:-80px;animation:drift1 18s ease-in-out infinite}\n"
        "    .o2{width:420px;height:420px;background:var(--violet);bottom:-140px;left:-100px;animation:drift2 22s ease-in-out infinite}\n"
        "    .o3{width:360px;height:360px;background:var(--cyan);top:40%;left:55%;animation:drift3 26s ease-in-out infinite}\n"
        "    @keyframes drift1{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-60px,40px) scale(1.1)}}\n"
        "    @keyframes drift2{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(50px,-50px) scale(1.15)}}\n"
        "    @keyframes drift3{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-40px,-30px) scale(.9)}}\n"
        "    .grid-overlay{position:fixed;inset:0;z-index:-1;background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:42px 42px;mask-image:radial-gradient(circle at 50% 30%,black,transparent 80%)}\n"
        "    header{background:rgba(8,10,16,.6);backdrop-filter:blur(18px);border-bottom:1px solid var(--border);padding:16px 30px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px;position:sticky;top:0;z-index:100}\n"
        "    .logo-area{display:flex;align-items:center;gap:14px}\n"
        "    .logo-area img{width:38px;height:38px;border-radius:10px;object-fit:contain;box-shadow:0 0 18px rgba(255,87,34,.35)}\n"
        "    .title{font-family:var(--display);font-size:18px;font-weight:900;letter-spacing:.08em;background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent;text-transform:uppercase}\n"
        "    .meta{color:var(--muted);font-size:11px;margin-top:2px;letter-spacing:.04em} .meta b{color:var(--text);font-weight:600}\n"
        "    .nav-links{display:flex;gap:12px;align-items:center;flex-wrap:wrap}\n"
        "    .nav-btn{color:var(--text);text-decoration:none;font-size:12px;font-weight:600;padding:8px 14px;border-radius:10px;border:1px solid var(--border);transition:.25s}\n"
        "    .nav-btn:hover{background:var(--surface2);border-color:var(--accent);color:var(--accent);box-shadow:0 0 16px rgba(255,87,34,.25)}\n"
        "    .btn-refresh{background:var(--grad);border:none;color:#0a0a0a;font-weight:700;cursor:pointer}\n"
        "    .btn-refresh:hover{filter:brightness(1.1);box-shadow:0 0 20px rgba(255,45,149,.45)}\n"
        "    .badge{display:inline-flex;align-items:center;gap:7px;padding:6px 14px;border-radius:100px;font-size:11px;font-weight:700;letter-spacing:.06em;border:1px solid;background:var(--surface);font-family:var(--display)}\n"
        "    .healthy{color:var(--green);border-color:rgba(0,230,118,.35);box-shadow:0 0 18px rgba(0,230,118,.15)}\n"
        "    .degraded{color:var(--red);border-color:rgba(255,82,82,.35);box-shadow:0 0 18px rgba(255,82,82,.15)}\n"
        "    .dot{width:8px;height:8px;border-radius:50%;background:currentColor;box-shadow:0 0 10px currentColor;animation:pulse 2s infinite}\n"
        "    @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.35;transform:scale(.7)}}\n"
        "    main{padding:30px;max-width:1180px;margin:0 auto}\n"
        "    .hero{display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:16px;margin-bottom:26px}\n"
        "    .hero h1{font-family:var(--display);font-size:30px;font-weight:900;letter-spacing:.04em}\n"
        "    .hero h1 span{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}\n"
        "    .hero p{color:var(--muted);font-size:12px;margin-top:4px}\n"
        "    .live{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted);font-family:var(--display);letter-spacing:.05em}\n"
        "    .live .dot{background:var(--green);color:var(--green)}\n"
        "    .section-title{font-family:var(--display);font-size:12px;font-weight:700;letter-spacing:.18em;color:var(--muted);text-transform:uppercase;margin:34px 0 16px;display:flex;align-items:center;gap:10px}\n"
        "    .section-title .ic{font-size:15px;filter:drop-shadow(0 0 6px rgba(34,211,238,.5))}\n"
        "    .section-title::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--border),transparent)}\n"
        "    .kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:16px}\n"
        "    .kpi{position:relative;background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:22px;overflow:hidden;backdrop-filter:blur(10px);transition:.35s cubic-bezier(.16,1,.3,1)}\n"
        "    .kpi::before{content:'';position:absolute;inset:0;background:var(--grad);opacity:0;transition:.35s;mix-blend-mode:overlay}\n"
        "    .kpi:hover{transform:translateY(-4px);border-color:rgba(255,87,34,.45);box-shadow:0 12px 40px rgba(0,0,0,.45),0 0 30px rgba(255,45,149,.12)}\n"
        "    .kpi:hover::before{opacity:.08}\n"
        "    .kpi .label{font-size:10px;color:var(--muted);letter-spacing:.14em;text-transform:uppercase;margin-bottom:12px;display:flex;align-items:center;gap:6px}\n"
        "    .kpi .value{font-family:var(--display);font-size:30px;font-weight:700;color:var(--text);line-height:1;font-variant-numeric:tabular-nums}\n"
        "    .kpi .value.accent{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}\n"
        "    .kpi .value.green{color:var(--green)} .kpi .value.red{color:var(--red)} .kpi .value.cyan{color:var(--cyan)}\n"
        "    .kpi .sub{font-size:11px;color:var(--muted);margin-top:9px}\n"
        "    .kpi .spark{margin-top:12px;width:100%;height:34px;display:block}\n"
        "    .ring-card{grid-column:span 2;display:flex;align-items:center;gap:22px}\n"
        "    .ring-wrap{position:relative;width:130px;height:130px;flex:0 0 auto}\n"
        "    .ring{transform:rotate(-90deg);width:130px;height:130px}\n"
        "    .ring-bg{fill:none;stroke:rgba(255,255,255,.08);stroke-width:9}\n"
        "    .ring-fg{fill:none;stroke:url(#rg);stroke-width:9;stroke-linecap:round;transition:stroke-dashoffset 1s cubic-bezier(.16,1,.3,1)}\n"
        "    .ring-center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}\n"
        "    .ring-center .big{font-family:var(--display);font-size:26px;font-weight:900;color:var(--text)}\n"
        "    .ring-center .small{font-size:9px;color:var(--muted);letter-spacing:.1em;text-transform:uppercase}\n"
        "    .table-container{background:var(--surface);border:1px solid var(--border);border-radius:18px;overflow:hidden;backdrop-filter:blur(10px)}\n"
        "    table{width:100%;border-collapse:collapse}\n"
        "    th{background:rgba(255,255,255,.02);color:var(--muted);font-size:10px;letter-spacing:.12em;text-transform:uppercase;padding:14px 18px;text-align:left;border-bottom:1px solid var(--border);font-family:var(--display);font-weight:700}\n"
        "    td{padding:13px 18px;border-bottom:1px solid var(--border);color:var(--text);font-size:13px}\n"
        "    tr:last-child td{border-bottom:none}\n"
        "    tbody tr{transition:background .2s}\n"
        "    tbody tr:hover td{background:rgba(255,87,34,.06)}\n"
        "    .cache-name{color:var(--cyan);font-weight:600;font-family:var(--display);font-size:12px;letter-spacing:.03em} .num{text-align:right;font-variant-numeric:tabular-nums;font-family:var(--display)}\n"
        "    .tag{font-size:9px;font-weight:800;letter-spacing:.08em;padding:3px 9px;border-radius:6px;text-transform:uppercase}\n"
        "    .tag.core{color:var(--green);background:rgba(0,230,118,.12);border:1px solid rgba(0,230,118,.3)}\n"
        "    .tag.legacy{color:var(--muted);background:rgba(255,255,255,.05);border:1px solid var(--border)}\n"
        "    .bar-track{display:inline-block;width:110px;height:7px;background:rgba(255,255,255,.07);border-radius:10px;vertical-align:middle;overflow:hidden}\n"
        "    .bar-fill{height:100%;border-radius:10px;transition:width .6s cubic-bezier(.16,1,.3,1)} .bar-label{font-size:12px;margin-left:9px;font-variant-numeric:tabular-nums;font-family:var(--display);color:var(--text)}\n"
        "    .bench-chart{display:flex;align-items:flex-end;gap:4px;height:90px;padding:14px 18px;background:var(--surface);border:1px solid var(--border);border-radius:18px;overflow-x:auto;backdrop-filter:blur(10px)}\n"
        "    .bench-bar-wrap{flex:1 0 18px;height:100%;display:flex;align-items:flex-end;justify-content:center}\n"
        "    .bench-bar{width:13px;border-radius:5px 5px 0 0;min-height:2px;transition:height .4s ease;box-shadow:0 0 8px rgba(34,211,238,.3)}\n"
        "    .empty{color:var(--muted);font-style:italic;text-align:center;padding:30px}\n"
        "    .endpoints{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}\n"
        "    .ep-link{display:inline-flex;align-items:center;gap:9px;padding:10px 18px;border:1px solid var(--border);border-radius:12px;background:var(--surface);color:var(--text);text-decoration:none;font-size:12px;font-weight:600;transition:.25s}\n"
        "    .ep-link:hover{border-color:var(--cyan);color:var(--cyan);background:var(--surface2);box-shadow:0 0 18px rgba(34,211,238,.18)}\n"
        "    .ep-link.active{background:linear-gradient(135deg,rgba(255,87,34,.18),rgba(34,211,238,.12));border-color:var(--accent);color:var(--accent)}\n"
        "    .ep-method{font-size:9px;font-weight:800;color:var(--muted);background:rgba(255,255,255,.06);padding:3px 7px;border-radius:5px;text-transform:uppercase;font-family:var(--display)}\n"
        "    footer{margin-top:60px;padding:26px 30px;border-top:1px solid var(--border);color:var(--muted);font-size:11px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;background:rgba(255,255,255,.015);letter-spacing:.03em}\n"
        "    footer a{color:var(--muted);text-decoration:none;transition:color .2s} footer a:hover{color:var(--accent)}\n"
        "    @media(max-width:640px){.ring-card{grid-column:span 1}.hero h1{font-size:23px}}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <div class='bg'><div class='orb o1'></div><div class='orb o2'></div><div class='orb o3'></div></div>\n"
        "  <div class='grid-overlay'></div>\n"
        "  <header>\n"
        "    <div class='logo-area'>\n"
        "      <img src='/logo.webp' alt='FFBB logo' onerror=\"this.style.display='none'\">\n"
        "      <div>\n"
        "        <div class='title'>FFBB MCP Dashboard</div>\n"
        f"        <div class='meta'>v<b>{_PACKAGE_VERSION}</b> &nbsp;&bull;&nbsp; spec <b>2025-11-25</b></div>\n"
        "      </div>\n"
        "    </div>\n"
        "    <div class='nav-links'>\n"
        "      <a href='/' class='nav-btn'>&#8592; Site</a>\n"
        f"      <span id='status-badge' class='badge {status_badge_cls}'><span class='dot'></span><span id='k-status-label'>{status_label}</span></span>\n"
        "      <button id='btn-refresh' class='nav-btn btn-refresh'>&#8635; Sync</button>\n"
        "    </div>\n"
        "  </header>\n"
        "  <main>\n"
        "    <div class='hero'>\n"
        "      <div>\n"
        "        <h1>Supervision <span>Temps R&eacute;el</span></h1>\n"
        "        <p>Pulse du serveur MCP FFBB &mdash; donn&eacute;es vivantes, mises &agrave; jour en continu</p>\n"
        "      </div>\n"
        "      <div class='live'><span class='dot'></span> LIVE &middot; MAJ <span id='last-updated'>&mdash;</span></div>\n"
        "    </div>\n"
        "    <div class='section-title'><span class='ic'>&#128201;</span> Monitoring Serveur</div>\n"
        "    <div class='kpi-grid'>\n"
        f"      <div class='kpi'><div class='label'>&#9211; Uptime</div><div id='k-uptime' class='value accent' style='font-size:21px'>{uptime_fmt}</div><div id='k-uptime-s' class='sub'>{uptime_s:.0f}s actifs</div></div>\n"
        f"      <div class='kpi'><div class='label'>&#128268; Appels API</div><div id='k-calls' class='value'>{calls}</div><div class='sub'>requ&ecirc;tes sortantes</div></div>\n"
        f"      <div class='kpi'><div class='label'>&#9888; Erreurs</div><div id='k-errors' class='value {error_class}'>{errors}</div><div id='k-error-rate' class='sub'>taux d'&eacute;chec {error_rate * 100:.1f}%</div></div>\n"
        f"      <div class='kpi'><div class='label'>&#9201; Latence moy.</div><div id='k-latency' class='value cyan'>{avg_lat_ms:.1f}<span style='font-size:14px;color:var(--muted)'>ms</span></div><div class='sub'>par appel API</div><canvas id='lat-spark' class='spark'></canvas></div>\n"
        f"      <div class='kpi'><div class='label'>&#128256; En cours</div><div id='k-inflight' class='value {inflight_class}'>{inflight}</div><div class='sub'>requ&ecirc;tes inflight</div></div>\n"
        "    </div>\n"
        "    <div class='section-title'><span class='ic'>&#128190;</span> Efficacit&eacute; du Cache</div>\n"
        "    <div class='kpi-grid'>\n"
        f"      <div class='kpi'><div class='label'>&#10003; Hits</div><div id='k-hits' class='value green'>{hits}</div></div>\n"
        f"      <div class='kpi'><div class='label'>&#10007; Misses</div><div id='k-misses' class='value'>{misses}</div></div>\n"
        f"      <div class='kpi ring-card'>\n"
        "        <div class='ring-wrap'>\n"
        f"          <svg class='ring' viewBox='0 0 130 130'><defs><linearGradient id='rg' x1='0' y1='0' x2='1' y2='1'><stop offset='0%' stop-color='#ff5722'/><stop offset='50%' stop-color='#ff2d95'/><stop offset='100%' stop-color='#22d3ee'/></linearGradient></defs><circle class='ring-bg' cx='65' cy='65' r='52'/><circle id='ring-fg' class='ring-fg' cx='65' cy='65' r='52' stroke-dasharray='326.7' stroke-dashoffset='{ring_offset:.1f}'/></svg>\n"
        f"          <div class='ring-center'><span id='k-hitratio' class='big'>{hit_pct:.1f}%</span><span class='small'>Hit Ratio</span></div>\n"
        "        </div>\n"
        f"        <div><div class='label' style='margin-bottom:6px'>Ratio global</div><div id='k-hitratio-sub' class='value' style='font-size:18px'>{hits} / {hits + misses}</div><div class='sub'>hits / total</div></div>\n"
        "      </div>\n"
        "    </div>\n"
        "    <div class='section-title'><span class='ic'>&#128204;</span> D&eacute;tails par Segment</div>\n"
        "    <div class='table-container'>\n"
        "      <table>\n"
        "        <thead><tr><th>Type de ressource</th><th style='text-align:right'>Hits</th><th style='text-align:right'>Misses</th><th style='text-align:right'>Total</th><th>Ratio</th></tr></thead>\n"
        f"        <tbody id='cache-tbody'>{cache_rows}</tbody>\n"
        "      </table>\n"
        "    </div>\n"
        "    <div class='section-title'><span class='ic'>&#129516;</span> Usage des Outils MCP</div>\n"
        "    <div class='kpi-grid'>\n"
        f"      <div class='kpi'><div class='label'>&#128273; Calls Core</div><div id='k-core' class='value green'>{core_calls}</div></div>\n"
        f"      <div class='kpi'><div class='label'>&#128274; Calls Legacy</div><div id='k-legacy' class='value'>{legacy_calls}</div></div>\n"
        f"      <div class='kpi'><div class='label'>&#128300; Tools distincts</div><div id='k-tools' class='value'>{len(tool_calls)}</div></div>\n"
        "    </div>\n"
        "    <div class='table-container' style='margin-top:16px'>\n"
        "      <table>\n"
        "        <thead><tr><th>Outil</th><th style='text-align:right'>Appels</th><th>Classe</th></tr></thead>\n"
        f"        <tbody id='tool-tbody'>{tool_rows}</tbody>\n"
        "      </table>\n"
        "    </div>\n"
        f"    {benchmark_html}\n"
        "    <div class='section-title'><span class='ic'>&#128279;</span> Points d'acc&egrave;s</div>\n"
        "    <div class='endpoints'>\n"
        "      <a class='ep-link' href='/'><span class='ep-method'>GET</span> Accueil</a>\n"
        "      <a class='ep-link' href='/health'><span class='ep-method'>GET</span> Sant&eacute;</a>\n"
        "      <a class='ep-link' href='/metrics'><span class='ep-method'>GET</span> Metrics</a>\n"
        "      <a class='ep-link active' href='/dashboard'><span class='ep-method'>GET</span> Dashboard</a>\n"
        "      <a class='ep-link' href='/mcp'><span class='ep-method'>POST</span> MCP</a>\n"
        "    </div>\n"
        "  </main>\n"
        "  <footer>\n"
        f"    <span>FFBB MCP Server &nbsp;&bull;&nbsp; <a href='https://github.com/nickdesi/FFBB-MCP-Server' target='_blank'>GitHub</a></span>\n"
        f"    <span>G&eacute;n&eacute;r&eacute; le {now_utc} &nbsp;&bull;&nbsp; v{_PACKAGE_VERSION}</span>\n"
        "  </footer>\n"
        "  <script>\n"
        "  (function(){\n"
        "    const CORE = " + str(sorted(_CORE_TOOLS)) + ";\n"
        "    const RING_C = 2 * Math.PI * 52;\n"
        "    let disp = {}, latHist = [], upBase = null, upT = 0;\n"
        "    const $ = id => document.getElementById(id);\n"
        "    function fmtInt(n){ return Math.round(n).toLocaleString('fr-FR'); }\n"
        "    function animate(id, target, dec){\n"
        "      const el = $(id); if(!el) return;\n"
        "      const start = disp[id] ?? 0; const t0 = performance.now(); const dur = 650;\n"
        "      function step(t){\n"
        "        const p = Math.min(1, (t - t0) / dur); const e = 1 - Math.pow(1 - p, 3);\n"
        "        const v = start + (target - start) * e;\n"
        "        el.textContent = dec ? v.toFixed(dec) : fmtInt(v);\n"
        "        if(p < 1) requestAnimationFrame(step); else disp[id] = target;\n"
        "      }\n"
        "      requestAnimationFrame(step);\n"
        "    }\n"
        "    function setText(id, txt){ const el = $(id); if(el) el.textContent = txt; }\n"
        "    function uptimeStr(s){\n"
        "      s = Math.max(0, Math.floor(s)); const d = Math.floor(s/86400), h = Math.floor(s%86400/3600), m = Math.floor(s%3600/60), x = s%60;\n"
        "      return d + 'j ' + String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(x).padStart(2,'0');\n"
        "    }\n"
        "    function barColor(p){ return p >= 80 ? '#00e676' : (p >= 50 ? '#ffab40' : '#ff5252'); }\n"
        "    function updateCache(cache){\n"
        "      const tb = $('cache-tbody'); if(!tb) return; let rows = '', hits = 0, total = 0;\n"
        "      for(const [name, s] of Object.entries(cache)){\n"
        "        hits += s.hits; total += s.total;\n"
        "        const p = (s.hit_ratio * 100); const col = barColor(p);\n"
        "        rows += \"<tr><td class='cache-name'>\" + name + \"</td><td class='num'>\" + fmtInt(s.hits) + \"</td><td class='num'>\" + fmtInt(s.misses) + \"</td><td class='num'>\" + fmtInt(s.total) + \"</td><td><div class='bar-track'><div class='bar-fill' style='width:\" + p.toFixed(1) + \"%;background:\" + col + \"'></div></div><span class='bar-label'>\" + p.toFixed(1) + \"%</span></td></tr>\";\n"
        "      }\n"
        "      tb.innerHTML = rows || \"<tr><td colspan='5' class='empty'>Aucune donnee de cache — aucun appel API effectue.</td></tr>\";\n"
        "      return { hits, total };\n"
        "    }\n"
        "    function updateTools(tc){\n"
        "      const tb = $('tool-tbody'); if(!tb) return; let rows = '', core = 0, legacy = 0;\n"
        "      const entries = Object.entries(tc).sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0]));\n"
        "      for(const [name, c] of entries){\n"
        "        const isCore = CORE.includes(name); isCore ? core += c : legacy += c;\n"
        "        rows += \"<tr><td class='cache-name'>\" + name + \"</td><td class='num'>\" + fmtInt(c) + \"</td><td><span class='tag ' + (isCore?'core':'legacy') + ''>\" + (isCore?'CORE':'LEGACY') + \"</span></td></tr>\";\n"
        "      }\n"
        "      tb.innerHTML = rows || \"<tr><td colspan='3' class='empty'>Aucun appel outil MCP observe.</td></tr>\";\n"
        "      return { core, legacy, n: entries.length };\n"
        "    }\n"
        "    function drawSpark(){\n"
        "      const c = $('lat-spark'); if(!c || latHist.length < 2) return;\n"
        "      const dpr = window.devicePixelRatio || 1; const w = c.clientWidth, h = c.clientHeight;\n"
        "      if(c.width !== Math.round(w*dpr)){ c.width = Math.round(w*dpr); c.height = Math.round(h*dpr); }\n"
        "      const ctx = c.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,w,h);\n"
        "      const max = Math.max.apply(null, latHist), min = Math.min.apply(null, latHist);\n"
        "      const pad = 3, rng = (max - min) || 1;\n"
        "      const X = i => pad + i * (w - 2*pad) / (latHist.length - 1);\n"
        "      const Y = v => h - pad - ((v - min) / rng) * (h - 2*pad);\n"
        "      const g = ctx.createLinearGradient(0,0,0,h); g.addColorStop(0,'rgba(34,211,238,.4)'); g.addColorStop(1,'rgba(34,211,238,0)');\n"
        "      ctx.beginPath(); ctx.moveTo(X(0), h-pad); latHist.forEach((v,i)=>ctx.lineTo(X(i),Y(v))); ctx.lineTo(X(latHist.length-1),h-pad); ctx.closePath(); ctx.fillStyle = g; ctx.fill();\n"
        "      ctx.beginPath(); latHist.forEach((v,i)=> i?ctx.lineTo(X(i),Y(v)):ctx.moveTo(X(i),Y(v))); ctx.strokeStyle='#22d3ee'; ctx.lineWidth=2; ctx.stroke();\n"
        "      const lx = X(latHist.length-1), ly = Y(latHist[latHist.length-1]); ctx.beginPath(); ctx.arc(lx,ly,3,0,7); ctx.fillStyle='#fff'; ctx.fill();\n"
        "    }\n"
        "    function refresh(){\n"
        "      fetch('/metrics.json').then(r => r.json()).then(d => {\n"
        "        const calls = (d.api_calls_success||0) + (d.api_calls_error||0);\n"
        "        const errors = d.api_calls_error||0;\n"
        "        const lat = (d.api_avg_latency_seconds||0) * 1000;\n"
        "        animate('k-calls', calls); animate('k-errors', errors);\n"
        "        setText('k-error-rate', 'taux d\\'echec ' + (errors/Math.max(1,calls)*100).toFixed(1) + '%');\n"
        "        animate('k-latency', lat, 1);\n"
        "        animate('k-inflight', d.api_inflight_requests||0);\n"
        "        const cv = updateCache(d.cache||{}); const tv = updateTools(d.tool_calls||{});\n"
        "        animate('k-hits', cv.hits); animate('k-misses', cv.misses);\n"
        "        animate('k-core', tv.core); animate('k-legacy', tv.legacy); animate('k-tools', tv.n);\n"
        "        const hr = cv.total ? cv.hits/cv.total : 0;\n"
        "        setText('k-hitratio', (hr*100).toFixed(1) + '%');\n"
        "        setText('k-hitratio-sub', cv.hits + ' / ' + cv.total);\n"
        "        const fg = $('ring-fg'); if(fg) fg.setAttribute('stroke-dashoffset', RING_C * (1 - hr));\n"
        "        const badge = $('status-badge'); const ok = (d.api_error_rate || 0) <= 0.05;\n"
        "        if(badge){ badge.className = 'badge ' + (ok?'healthy':'degraded'); setText('k-status-label', ok?'HEALTHY':'DEGRADED'); }\n"
        "        upBase = d.uptime_seconds||0; upT = Date.now();\n"
        "        setText('last-updated', new Date().toLocaleTimeString('fr-FR'));\n"
        "        latHist.push(lat); if(latHist.length > 40) latHist.shift(); drawSpark();\n"
        "      }).catch(()=>{});\n"
        "    }\n"
        "    function tick(){\n"
        "      if(upBase !== null){ const s = upBase + (Date.now() - upT)/1000; setText('k-uptime', uptimeStr(s)); setText('k-uptime-s', Math.floor(s) + 's actifs'); }\n"
        "    }\n"
        "    $('btn-refresh').addEventListener('click', () => location.reload());\n"
        "    window.addEventListener('resize', drawSpark);\n"
        "    refresh(); setInterval(refresh, 5000); setInterval(tick, 1000);\n"
        "  })();\n"
        "  </script>\n"
        "</body>\n"
        "</html>"
    )
    return html
