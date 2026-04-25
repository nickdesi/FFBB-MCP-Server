"""Dashboard HTML pour le serveur FFBB MCP — route /dashboard."""
import datetime

from .metrics import get_snapshot
from . import __version__ as _PACKAGE_VERSION


def _build_dashboard_html() -> str:
    snap = get_snapshot()
    now_utc = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

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
        "    :root{--bg:#0a0a0a;--surface:rgba(255,255,255,0.03);--surface2:rgba(255,255,255,0.06);--border:rgba(255,255,255,0.1);--accent:#ff5722;--green:#00e676;--red:#ff5252;--yellow:#ffab40;--text:#e0e0e0;--muted:#999;--mono:'JetBrains Mono','Fira Code','Courier New',monospace}\n"
        "    *{box-sizing:border-box;margin:0;padding:0}\n"
        "    body{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:13px;line-height:1.5;min-height:100vh;overflow-x:hidden}\n"
        "    .bg-glow{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none;overflow:hidden}\n"
        "    .glow-orb{position:absolute;border-radius:50%;filter:blur(100px);opacity:0.1}\n"
        "    .glow-1{top:-10%;right:-10%;width:400px;height:400px;background:var(--accent)}\n"
        "    header{background:rgba(10,10,10,0.8);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);padding:16px 28px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;position:sticky;top:0;z-index:100}\n"
        "    .logo-area{display:flex;align-items:center;gap:12px}\n"
        "    .logo-area img{width:32px;height:32px;border-radius:8px;object-fit:contain;box-shadow:0 0 15px rgba(255,87,34,0.2)}\n"
        "    .title{font-size:16px;font-weight:700;color:var(--accent);letter-spacing:.05em;text-transform:uppercase}\n"
        "    .meta{color:var(--muted);font-size:10px;margin-top:2px} .meta span{color:var(--text)}\n"
        "    .nav-links{display:flex;gap:16px;align-items:center}\n"
        "    .nav-btn{color:var(--text);text-decoration:none;font-size:11px;font-weight:600;padding:6px 12px;border-radius:6px;border:1px solid var(--border);transition:all 0.2s}\n"
        "    .nav-btn:hover{background:var(--surface2);border-color:var(--accent);color:var(--accent)}\n"
        "    .badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:100px;font-size:10px;font-weight:700;letter-spacing:.05em;border:1px solid;background:var(--surface)}\n"
        "    .healthy{color:var(--green);border-color:rgba(0,230,118,0.3)}\n"
        "    .degraded{color:var(--red);border-color:rgba(255,82,82,0.3)}\n"
        "    .dot{width:6px;height:6px;border-radius:50%;background:currentColor;animation:pulse 2s infinite}\n"
        "    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}\n"
        "    main{padding:24px 28px;max-width:1100px;margin:0 auto}\n"
        "    .section-title{font-size:10px;font-weight:700;letter-spacing:.15em;color:var(--muted);text-transform:uppercase;margin-bottom:16px;margin-top:32px;display:flex;align-items:center;gap:8px}\n"
        "    .section-title::after{content:'';flex:1;height:1px;background:var(--border)}\n"
        "    .kpi-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}\n"
        "    .kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;transition:all .3s cubic-bezier(0.16, 1, 0.3, 1);backdrop-filter:blur(5px)}\n"
        "    .kpi:hover{border-color:rgba(255,87,34,0.4);transform:translateY(-2px);background:var(--surface2)}\n"
        "    .kpi .label{font-size:10px;color:var(--muted);letter-spacing:.1em;text-transform:uppercase;margin-bottom:10px}\n"
        "    .kpi .value{font-size:28px;font-weight:700;color:var(--text);line-height:1}\n"
        "    .kpi .value.accent{color:var(--accent)} .kpi .value.green{color:var(--green)} .kpi .value.red{color:var(--red)}\n"
        "    .kpi .sub{font-size:10px;color:var(--muted);margin-top:8px}\n"
        "    .table-container{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;backdrop-filter:blur(5px)}\n"
        "    table{width:100%;border-collapse:collapse}\n"
        "    th{background:rgba(255,255,255,0.02);color:var(--muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding:12px 16px;text-align:left;border-bottom:1px solid var(--border)}\n"
        "    td{padding:12px 16px;border-bottom:1px solid var(--border);color:var(--text)}\n"
        "    tr:last-child td{border-bottom:none}\n"
        "    tr:hover td{background:rgba(255,87,34,.05)}\n"
        "    .cache-name{color:var(--accent);font-weight:600} .num{text-align:right;font-variant-numeric:tabular-nums}\n"
        "    .bar-track{display:inline-block;width:100px;height:6px;background:var(--border);border-radius:10px;vertical-align:middle;overflow:hidden}\n"
        "    .bar-fill{height:100%;border-radius:10px;transition:width .4s ease} .bar-label{font-size:11px;margin-left:8px;font-variant-numeric:tabular-nums}\n"
        "    .empty{color:var(--muted);font-style:italic;text-align:center;padding:30px}\n"
        "    .endpoints{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}\n"
        "    .ep-link{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);text-decoration:none;font-size:11px;transition:all .2s}\n"
        "    .ep-link:hover{border-color:var(--accent);color:var(--accent);background:var(--surface2)}\n"
        "    .ep-link.active{background:rgba(255,87,34,0.1);border-color:var(--accent);color:var(--accent)}\n"
        "    .ep-method{font-size:9px;font-weight:700;color:var(--muted);background:rgba(255,255,255,0.05);padding:2px 6px;border-radius:4px;text-transform:uppercase}\n"
        "    footer{margin-top:60px;padding:24px 28px;border-top:1px solid var(--border);color:var(--muted);font-size:10px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:12px;background:rgba(255,255,255,0.01)}\n"
        "    footer a{color:var(--muted);text-decoration:none;transition:color 0.2s} footer a:hover{color:var(--accent)}\n"
        "    .refresh-note{color:var(--muted);font-size:10px;display:flex;align-items:center;gap:8px}\n"
        "    .spin{display:inline-block;animation:spin 3s linear infinite;font-size:14px;color:var(--accent)}\n"
        "    @keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <div class='bg-glow'><div class='glow-orb glow-1'></div></div>\n"
        "  <header>\n"
        "    <div class='logo-area'>\n"
        "      <img src='/logo.webp' alt='FFBB logo' onerror=\"this.style.display='none'\">\n"
        "      <div>\n"
        "        <div class='title'>FFBB MCP DASHBOARD</div>\n"
        "        <div class='meta'>v<span>{_PACKAGE_VERSION}</span> &nbsp;&#183;&nbsp; spec <span>2025-11-25</span></div>\n"
        "      </div>\n"
        "    </div>\n"
        "    <div class='nav-links'>\n"
        "      <a href='/' class='nav-btn'>&#8592; Retour au site</a>\n"
        "      <span class='badge {status_badge_cls}'><span class='dot'></span>{status_label}</span>\n"
        "      <span class='refresh-note'><span class='spin'>&#8635;</span></span>\n"
        "    </div>\n"
        "  </header>\n"
        "  <main>\n"
        "    <div class='section-title'>&#128201; Monitoring Serveur</div>\n"
        "    <div class='kpi-grid'>\n"
        f"      <div class='kpi'><div class='label'>Uptime</div><div class='value accent' style='font-size:20px'>{uptime_fmt}</div><div class='sub'>{uptime_s:.0f}s actifs</div></div>\n"
        f"      <div class='kpi'><div class='label'>Appels API</div><div class='value'>{calls}</div><div class='sub'>requetes sortantes</div></div>\n"
        f"      <div class='kpi'><div class='label'>Erreurs</div><div class='value {error_class}'>{errors}</div><div class='sub'>taux d'echec {error_rate*100:.1f}%</div></div>\n"
        f"      <div class='kpi'><div class='label'>Latence</div><div class='value'>{avg_lat_ms:.1f}<span style='font-size:14px;color:var(--muted)'>ms</span></div><div class='sub'>moyenne par appel</div></div>\n"
        f"      <div class='kpi'><div class='label'>En cours</div><div class='value {inflight_class}'>{inflight}</div><div class='sub'>requetes inflight</div></div>\n"
        "    </div>\n"
        "    <div class='section-title'>&#128190; Efficacite du Cache</div>\n"
        "    <div class='kpi-grid'>\n"
        f"      <div class='kpi'><div class='label'>Hits</div><div class='value green'>{hits}</div></div>\n"
        f"      <div class='kpi'><div class='label'>Misses</div><div class='value'>{misses}</div></div>\n"
        f"      <div class='kpi' style='grid-column:span 2'><div class='label'>Hit Ratio Global</div>\n"
        f"        <div style='display:flex;align-items:center;gap:16px;margin-top:10px'>\n"
        f"          <div class='bar-track' style='width:100%;height:10px'><div class='bar-fill' style='width:{hit_pct:.1f}%;background:{global_bar_color}'></div></div>\n"
        f"          <span style='font-size:22px;font-weight:700;color:{global_bar_color};min-width:60px'>{hit_pct:.1f}%</span>\n"
        f"        </div></div>\n"
        "    </div>\n"
        "    <div class='section-title'>&#128204; Details par Segment</div>\n"
        "    <div class='table-container'>\n"
        "      <table>\n"
        "        <thead><tr><th>Type de ressource</th><th style='text-align:right'>Hits</th><th style='text-align:right'>Misses</th><th style='text-align:right'>Total</th><th>Ratio</th></tr></thead>\n"
        f"        <tbody>{cache_rows}</tbody>\n"
        "      </table>\n"
        "    </div>\n"
        "    <div class='section-title'>&#128279; Points d'acces</div>\n"
        "    <div class='endpoints'>\n"
        "      <a class='ep-link' href='/'><span class='ep-method'>GET</span> Accueil site</a>\n"
        "      <a class='ep-link' href='/health'><span class='ep-method'>GET</span> Sante</a>\n"
        "      <a class='ep-link' href='/metrics'><span class='ep-method'>GET</span> Metrics</a>\n"
        "      <a class='ep-link active' href='/dashboard'><span class='ep-method'>GET</span> Dashboard</a>\n"
        "      <a class='ep-link' href='/mcp'><span class='ep-method'>POST</span> MCP Endpoint</a>\n"
        "    </div>\n"
        "  </main>\n"
        "  <footer>\n"
        f"    <span>FFBB MCP Server &nbsp;&#183;&nbsp; <a href='https://github.com/nickdesi/FFBB-MCP-Server' target='_blank'>GitHub</a></span>\n"
        f"    <span>Genere le {now_utc} &nbsp;&#183;&nbsp; v{_PACKAGE_VERSION}</span>\n"
        "  </footer>\n"
        "</body>\n"
        "</html>"
    )
    return html
