"""Dashboard HTML pour le serveur FFBB MCP — route /dashboard."""

from .metrics import get_snapshot
from . import __version__ as _PACKAGE_VERSION


def _build_dashboard_html() -> str:
    snap = get_snapshot()

    uptime_s = snap["uptime_seconds"]
    days = int(uptime_s // 86400)
    hours = int((uptime_s % 86400) // 3600)
    minutes = int((uptime_s % 3600) // 60)
    seconds = int(uptime_s % 60)
    uptime_fmt = f"{days}j {hours:02d}:{minutes:02d}:{seconds:02d}"

    calls = snap["api_calls_total"]
    errors = snap["api_errors_total"]
    error_rate = snap["api_error_rate"]
    avg_lat_ms = snap["api_avg_latency_seconds"] * 1000
    inflight = snap["api_inflight_requests"]
    hits = snap["cache_hits_total"]
    misses = snap["cache_misses_total"]
    hit_ratio = snap["cache_hit_ratio_global"]
    cache_stats = snap.get("cache", {})

    status_badge_cls = "healthy" if errors == 0 else "degraded"
    status_label = "HEALTHY" if errors == 0 else "DEGRADED"

    cache_rows = ""
    for name, stat in cache_stats.items():
        ratio_pct = stat["hit_ratio"] * 100
        bar_color = "#00e676" if ratio_pct >= 80 else ("#ffab40" if ratio_pct >= 50 else "#ff5252")
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
    global_bar_color = "#00e676" if hit_pct >= 80 else ("#ffab40" if hit_pct >= 50 else "#ff5252")
    inflight_class = "accent" if inflight > 0 else ""
    error_class = "red" if errors > 0 else "green"

    html = (
        "<!DOCTYPE html>\n"
        "<html lang='fr'>\n"
        "<head>\n"
        "  <meta charset='UTF-8' />\n"
        "  <meta name='viewport' content='width=device-width, initial-scale=1.0' />\n"
        "  <meta http-equiv='refresh' content='10' />\n"
        "  <title>FFBB MCP Dashboard</title>\n"
        "  <style>\n"
        "    :root{--bg:#0d0d0d;--surface:#161616;--surface2:#1e1e1e;--border:#2a2a2a;--accent:#f97316;--green:#00e676;--red:#ff5252;--yellow:#ffab40;--text:#e0e0e0;--muted:#888;--mono:'JetBrains Mono','Fira Code','Courier New',monospace}\n"
        "    *{box-sizing:border-box;margin:0;padding:0}\n"
        "    body{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:13px;line-height:1.5;min-height:100vh}\n"
        "    header{background:var(--surface);border-bottom:1px solid var(--border);padding:14px 28px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}\n"
        "    .title{font-size:16px;font-weight:700;color:var(--accent);letter-spacing:.05em}\n"
        "    .meta{color:var(--muted);font-size:11px} .meta span{color:var(--text)}\n"
        "    .badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:.08em;border:1px solid}\n"
        "    .healthy{color:var(--green);border-color:var(--green);background:rgba(0,230,118,.08)}\n"
        "    .degraded{color:var(--red);border-color:var(--red);background:rgba(255,82,82,.08)}\n"
        "    .dot{width:7px;height:7px;border-radius:50%;background:currentColor}\n"
        "    main{padding:24px 28px;max-width:1200px;margin:0 auto}\n"
        "    .section-title{font-size:10px;font-weight:700;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;margin-bottom:12px;margin-top:28px;border-bottom:1px solid var(--border);padding-bottom:6px}\n"
        "    .kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}\n"
        "    .kpi{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:16px}\n"
        "    .kpi .label{font-size:10px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}\n"
        "    .kpi .value{font-size:28px;font-weight:700;color:var(--text);line-height:1}\n"
        "    .kpi .value.accent{color:var(--accent)} .kpi .value.green{color:var(--green)} .kpi .value.red{color:var(--red)}\n"
        "    .kpi .sub{font-size:10px;color:var(--muted);margin-top:6px}\n"
        "    table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:hidden}\n"
        "    th{background:var(--surface2);color:var(--muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding:10px 14px;text-align:left;border-bottom:1px solid var(--border)}\n"
        "    td{padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text)}\n"
        "    tr:last-child td{border-bottom:none}\n"
        "    .cache-name{color:var(--accent);font-weight:600} .num{text-align:right;font-variant-numeric:tabular-nums}\n"
        "    .bar-track{display:inline-block;width:100px;height:6px;background:var(--border);border-radius:3px;vertical-align:middle;overflow:hidden}\n"
        "    .bar-fill{height:100%;border-radius:3px} .bar-label{font-size:11px;margin-left:8px;font-variant-numeric:tabular-nums}\n"
        "    .empty{color:var(--muted);font-style:italic;text-align:center;padding:20px}\n"
        "    .endpoints{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}\n"
        "    .ep-link{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text);text-decoration:none;font-size:12px}\n"
        "    .ep-link:hover{border-color:var(--accent);color:var(--accent)}\n"
        "    .ep-method{font-size:9px;color:var(--muted);background:var(--surface2);padding:2px 5px;border-radius:3px}\n"
        "    footer{margin-top:40px;padding:16px 28px;border-top:1px solid var(--border);color:var(--muted);font-size:10px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}\n"
        "    footer a{color:var(--muted);text-decoration:none} footer a:hover{color:var(--accent)}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <header>\n"
        f"    <div><div class='title'>&#127936; FFBB MCP SERVER</div>\n"
        f"    <div class='meta'>v<span>{_PACKAGE_VERSION}</span> &nbsp;&#183;&nbsp; transport <span>streamable-http</span> &nbsp;&#183;&nbsp; spec <span>2025-11-25</span></div></div>\n"
        f"    <div style='display:flex;align-items:center;gap:16px'>\n"
        f"      <span class='badge {status_badge_cls}'><span class='dot'></span>{status_label}</span>\n"
        f"      <span style='color:var(--muted);font-size:10px'>&#10227; auto-refresh 10s</span>\n"
        f"    </div>\n"
        f"  </header>\n"
        "  <main>\n"
        "    <div class='section-title'>Serveur</div>\n"
        "    <div class='kpi-grid'>\n"
        f"      <div class='kpi'><div class='label'>Uptime</div><div class='value accent' style='font-size:20px'>{uptime_fmt}</div><div class='sub'>{uptime_s:.0f}s depuis demarrage</div></div>\n"
        f"      <div class='kpi'><div class='label'>Appels API FFBB</div><div class='value'>{calls}</div><div class='sub'>total cumule</div></div>\n"
        f"      <div class='kpi'><div class='label'>Erreurs API</div><div class='value {error_class}'>{errors}</div><div class='sub'>taux {error_rate*100:.1f}%</div></div>\n"
        f"      <div class='kpi'><div class='label'>Latence moy.</div><div class='value'>{avg_lat_ms:.1f}<span style='font-size:14px;color:var(--muted)'>ms</span></div><div class='sub'>par appel API</div></div>\n"
        f"      <div class='kpi'><div class='label'>Inflight</div><div class='value {inflight_class}'>{inflight}</div><div class='sub'>requetes en cours</div></div>\n"
        "    </div>\n"
        "    <div class='section-title'>Cache Global</div>\n"
        "    <div class='kpi-grid'>\n"
        f"      <div class='kpi'><div class='label'>Hits</div><div class='value green'>{hits}</div></div>\n"
        f"      <div class='kpi'><div class='label'>Misses</div><div class='value'>{misses}</div></div>\n"
        f"      <div class='kpi' style='grid-column:span 2'><div class='label'>Hit Ratio Global</div>\n"
        f"        <div style='display:flex;align-items:center;gap:12px;margin-top:8px'>\n"
        f"          <div class='bar-track' style='width:100%;height:10px'><div class='bar-fill' style='width:{hit_pct:.1f}%;background:{global_bar_color}'></div></div>\n"
        f"          <span style='font-size:22px;font-weight:700;color:{global_bar_color};min-width:52px'>{hit_pct:.1f}%</span>\n"
        f"        </div></div>\n"
        "    </div>\n"
        "    <div class='section-title'>Cache par type</div>\n"
        "    <table>\n"
        "      <thead><tr><th>Cache</th><th style='text-align:right'>Hits</th><th style='text-align:right'>Misses</th><th style='text-align:right'>Total</th><th>Hit Ratio</th></tr></thead>\n"
        f"      <tbody>{cache_rows}</tbody>\n"
        "    </table>\n"
        "    <div class='section-title'>Endpoints</div>\n"
        "    <div class='endpoints'>\n"
        "      <a class='ep-link' href='/'><span class='ep-method'>GET</span> /</a>\n"
        "      <a class='ep-link' href='/health'><span class='ep-method'>GET</span> /health</a>\n"
        "      <a class='ep-link' href='/metrics'><span class='ep-method'>GET</span> /metrics</a>\n"
        "      <a class='ep-link' href='/dashboard'><span class='ep-method'>GET</span> /dashboard</a>\n"
        "      <a class='ep-link' href='/mcp'><span class='ep-method'>POST</span> /mcp</a>\n"
        "    </div>\n"
        "  </main>\n"
        f"  <footer>\n"
        f"    <span>FFBB MCP Server &nbsp;&#183;&nbsp; <a href='https://github.com/nickdesi/FFBB-MCP-Server' target='_blank'>github.com/nickdesi/FFBB-MCP-Server</a></span>\n"
        f"    <span>uptime {uptime_fmt} &nbsp;&#183;&nbsp; v{_PACKAGE_VERSION}</span>\n"
        f"  </footer>\n"
        "</body>\n"
        "</html>"
    )
    return html
