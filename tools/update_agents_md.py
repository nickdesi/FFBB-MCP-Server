#!/usr/bin/env python3
"""Génère AGENTS.md à partir du code source (server.py, resources.py, services.py)."""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = ROOT / "src" / "ffbb_mcp" / "server.py"
RESOURCES_PY = ROOT / "src" / "ffbb_mcp" / "resources.py"
SERVICES_DIR = ROOT / "src" / "ffbb_mcp" / "services"
AGENTS_MD = ROOT / "AGENTS.md"


def extract_tools() -> list[dict]:
    """Parse server.py et extrait chaque @mcp.tool() avec son nom, docstring et ligne."""
    tree = ast.parse(SERVER_PY.read_text())
    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            tool_name = _get_mcp_tool_name(deco)
            if tool_name:
                docstring = ast.get_docstring(node) or ""
                first_line = docstring.strip().split("\n")[0] if docstring else ""
                tools.append(
                    {
                        "name": tool_name,
                        "func_name": node.name,
                        "summary": first_line.strip().rstrip("."),
                        "line": node.lineno,
                    }
                )
    return tools


def _get_mcp_tool_name(deco: ast.expr) -> str | None:
    """Extrait le paramètre name= du décorateur @mcp.tool(name='...')."""
    if (
        isinstance(deco, ast.Call)
        and isinstance(deco.func, ast.Attribute)
        and isinstance(deco.func.value, ast.Name)
        and deco.func.value.id == "mcp"
        and deco.func.attr == "tool"
    ):
        for kw in deco.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return None


def extract_resources() -> list[dict]:
    """Parse resources.py et extrait chaque @mcp.resource() URI."""
    tree = ast.parse(RESOURCES_PY.read_text())
    resources = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            uri = _resource_uri(deco)
            if uri:
                docstring = ast.get_docstring(node) or ""
                first_line = docstring.strip().split("\n")[0] if docstring else ""
                resources.append(
                    {
                        "uri": uri,
                        "summary": first_line.strip().rstrip("."),
                        "line": node.lineno,
                    }
                )
    return resources


def _resource_uri(deco: ast.expr) -> str | None:
    if (
        isinstance(deco, ast.Call)
        and isinstance(deco.func, ast.Attribute)
        and isinstance(deco.func.value, ast.Name)
        and deco.func.value.id == "mcp"
        and deco.func.attr == "resource"
        and deco.args
        and isinstance(deco.args[0], ast.Constant)
    ):
        return str(deco.args[0].value)
    return None


def extract_services() -> list[dict]:
    """Liste les fonctions publiques (async def ffbb_*) dans le package services."""
    services = []
    for py_file in sorted(SERVICES_DIR.glob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef,)) and node.name.startswith(
                "ffbb_"
            ):
                docstring = ast.get_docstring(node) or ""
                first_line = docstring.strip().split("\n")[0] if docstring else ""
                services.append(
                    {
                        "name": node.name,
                        "summary": first_line.strip().rstrip("."),
                        "line": node.lineno,
                    }
                )
    return services


def extract_env_vars() -> list[dict]:
    """Extrait les variables d'environnement de tous les fichiers src/ffbb_mcp/."""
    env_vars: dict[str, str] = {}
    src_dir = ROOT / "src" / "ffbb_mcp"
    for py_file in sorted(src_dir.rglob("*.py")):
        text = py_file.read_text()
        # os.environ.get("VAR", "default")
        for m in re.finditer(
            r"""os\.environ\.get\(["']([^"']+)["']\s*(?:,\s*["']([^"']*)["'])?\)""",
            text,
        ):
            var_name = m.group(1)
            default = m.group(2) or ""
            if var_name not in env_vars:
                env_vars[var_name] = default
        # _read_positive_int_env("VAR", default_int)
        for m in re.finditer(
            r"""_read_positive_int_env\(["']([^"']+)["']\s*,\s*(\d+)\)""", text
        ):
            var_name = m.group(1)
            default = m.group(2)
            if var_name not in env_vars:
                env_vars[var_name] = default
    return [{"name": k, "default": v} for k, v in env_vars.items()]


def extract_architecture() -> str:
    """Retourne l'arbre des fichiers source avec description."""
    descriptions = {
        "__init__.py": "Version du package",
        "__main__.py": "Point d'entrée CLI",
        "_state.py": "State global (caches, inflight)",
        "aliases.py": "Alias clubs + cache acronymes persistant",
        "app_factory.py": "Starlette app + middlewares",
        "benchmark.py": "Benchmark performance",
        "cache_strategy.py": "TTL dynamique selon fenêtres de match",
        "client.py": "FFBBDataClient factory + token refresh",
        "dashboard.py": "Dashboard HTML",
        "metrics.py": "Prometheus metrics + health snapshot",
        "prompts.py": "Prompts MCP réutilisables",
        "resources.py": "Resources MCP (ffbb://saisons, etc.)",
        "routes.py": "Routes HTTP (health, metrics, dashboard, docs, etc.)",
        "server.py": "Tools MCP + main()",
        "services/": "Logique métier modularisée",
        "utils.py": "serialize_model, parse_categorie, prune_payload",
    }
    lines = ["src/ffbb_mcp/"]
    keys = sorted(descriptions.keys())
    for i, k in enumerate(keys):
        is_last = i == len(keys) - 1
        prefix = "└── " if is_last else "├── "
        if k == "services/":
            lines.append(f"{prefix}{k:<22s} # {descriptions[k]}")
            sub_files = sorted([f.name for f in SERVICES_DIR.glob("*.py")])
            for j, sf in enumerate(sub_files):
                sub_is_last = j == len(sub_files) - 1
                sub_prefix = "│   └── " if sub_is_last else "│   ├── "
                sub_desc = {
                    "__init__.py": "Point d'entrée et factory de services",
                    "club.py": "Service de gestion des clubs",
                    "common.py": "Helpers et base services partagés",
                    "poule.py": "Service de gestion des poules",
                    "salle.py": "Service de gestion des salles",
                    "search.py": "Service de recherche multicritère",
                    "warmup.py": "Service de préchauffage du cache",
                }.get(sf, "Module de service")
                lines.append(f"{sub_prefix}{sf:<18s} # {sub_desc}")
        else:
            lines.append(f"{prefix}{k:<22s} # {descriptions[k]}")
    return "\n".join(lines)


def count_lines(filepath: Path) -> int:
    return len(filepath.read_text().splitlines())


def count_services_lines() -> int:
    """Compte le nombre de lignes de tous les fichiers .py du package services."""
    total = 0
    for py_file in SERVICES_DIR.glob("*.py"):
        total += len(py_file.read_text().splitlines())
    return total


ENV_DESCRIPTIONS = {
    "MCP_MODE": "Mode de transport (`stdio` / `streamable-http`)",
    "PORT": "Port d'écoute HTTP",
    "HOST": "Interface d'écoute",
    "PUBLIC_URL": "URL publique pour liens/sitemap",
    "ALLOWED_HOSTS": "Hosts autorisés (DNS rebinding protection)",
    "ALLOWED_ORIGINS": "Origins CORS",
    "FFBB_LOG_LEVEL": "Niveau de log",
    "MAX_CONCURRENT_FFBB": "Concurrence max appels API FFBB",
    "FFBB_ENABLE_BENCHMARK": "Activer endpoint `/benchmark/run` (sécurité)",
    "FFBB_MCP_PRUNE_LIMIT": "Limite troncature payload",
    "FFBB_MAX_CALENDAR_MATCHES": "Max rencontres retournées",
    "FFBB_POULE_FETCH_CONCURRENCY": "Concurrence max fetch poules",
    "FFBB_CACHE_TTL_*": "TTL par type de cache (voir cache_strategy.py)",
    "TRUSTED_PROXY_HOSTS": "Proxies de confiance",
    "FFBB_CACHE_BACKEND": "Choix du backend de cache HTTP (`sqlite` ou `redis`)",
    "FFBB_REDIS_URL": "URL de connexion à l'instance Redis si backend=redis",
    "FFBB_CACHE_EXPIRE_AFTER": "TTL en secondes pour le cache HTTP court de session (défaut : 30)",
    "ENABLE_DNS_PROTECTION": "Activer/désactiver explicitement la protection contre le DNS rebinding",
    "XDG_CACHE_HOME": "Dossier racine pour stocker les fichiers de cache persistants (ex: acronymes, benchmark)",
    "FFBB_WARMUP_ORGANISMES": "Liste d'organisme_id séparés par des virgules à préchauffer au démarrage",
    "FFBB_WARMUP_CONCURRENCY": "Concurrence maximale lors du préchauffage du cache",
    "FFBB_KNOWN_CLUB_IDS": "Override JSON de la liste d'organisme_id connus pour les prompts MCP (fallback : _DEFAULT_KNOWN_CLUB_IDS)",
}


def generate_agents_md() -> str:
    tools = extract_tools()
    resources = extract_resources()
    env_vars = extract_env_vars()
    architecture = extract_architecture()

    server_lines = count_lines(SERVER_PY)
    services_lines = count_services_lines()

    # Workflow FFBB — liste des tools dans l'ordre logique
    workflow_tools = [
        "ffbb_search",
        "ffbb_resolve_team",
        "ffbb_team_summary",
        "ffbb_bilan",
        "ffbb_club",
        "ffbb_get",
        "ffbb_next_match",
        "ffbb_last_result",
        "ffbb_lives",
        "ffbb_bilan_saison",
        "ffbb_saisons",
        "ffbb_version",
    ]

    # Construire le bloc workflow
    workflow_lines = []
    for i, name in enumerate(workflow_tools, 1):
        tool = next((t for t in tools if t["name"] == name), None)
        if tool:
            workflow_lines.append(f"{i}. **{tool['name']}** → {tool['summary']}")

    # Construire le bloc architecture avec compteurs de lignes
    arch_lines = architecture.split("\n")
    for idx, line in enumerate(arch_lines):
        if "server.py" in line:
            arch_lines[idx] = line.replace(
                "# Tools MCP + main()", f"# Tools MCP + main() (≈{server_lines} lignes)"
            )
        elif "services/" in line:
            arch_lines[idx] = line.replace(
                "# Logique métier modularisée",
                f"# Logique métier modularisée (≈{services_lines} lignes)",
            )

    # Merge: extracted vars + whitelist fallback
    extracted_names = {ev["name"] for ev in env_vars}
    env_table_rows = []
    for ev in env_vars:
        desc = ENV_DESCRIPTIONS.get(ev["name"], "")
        if desc:
            env_table_rows.append(f"| `{ev['name']}` | `{ev['default']}` | {desc} |")
    for name, desc in ENV_DESCRIPTIONS.items():
        if name not in extracted_names:
            env_table_rows.append(f"| `{name}` | — | {desc} |")

    # Ressources
    resource_lines = []
    for r in resources:
        resource_lines.append(f"- `{r['uri']}` → {r['summary']}")

    NL = "\n"
    content = f"""# FFBB MCP Server

> ⚠️ **Fichier auto-généré** par `tools/update_agents_md.py` — ne pas modifier manuellement.
> Dernière mise à jour : FFBB MCP server | server.py: {server_lines} lignes | services.py: {services_lines} lignes

## Langue
Tous les documents de travail (walkthrough.md, implementation_plan.md) DOIVENT être en français.

## Persona
Expert en basketball français. Accès au serveur MCP FFBB (ffbb.desimone.fr) connecté aux données officielles FFBB.

## Workflow FFBB (Outils MCP)
{NL.join(workflow_lines)}

## Ressources MCP
{NL.join(resource_lines)}

## Règles de comportement
- Appelle TOUJOURS un outil MCP avant de répondre
- OBLIGATION ABSOLUE : Utiliser TOUJOURS le préfixe 'rtk' pour TOUTES les commandes shell exécutées dans le terminal (ex: 'rtk uv run ...', 'rtk git ...')
- Si plusieurs résultats, liste et demande confirmation
- Réponds toujours en français
- Si API ne répond pas, dis-le clairement
- Scores live : précise "données en temps réel, mises à jour toutes les 30s"
- Réutilise les `organisme_id` résolus dans la conversation (ne pas re-rechercher)

## Règles strictes (outils FFBB)
- **INTERDIT** : `ffbb_get(type='poule')` pour chercher un score ou match
- **INTERDIT** : Déduire un score depuis le classement
- **INTERDIT** : Déclarer qu'un score "n'est pas disponible" sans avoir vérifié
- **OBLIGATOIRE** : Présenter un résultat de match AVEC le classement complet (paniers_marqués, paniers_encaissés)
- **SINGULIER vs PLURIEL** : "prochain match" → `ffbb_next_match` · "prochains matchs" → `ffbb_club(action='calendrier')`
- **Catégorie ambiguë** : Appeler `ffbb_resolve_team` AVANT `ffbb_next_match`/`ffbb_last_result` si pas de numéro d'équipe

## Karpathy Guidelines (Règles de développement)
Ces directives inspirées d'Andrej Karpathy visent à éliminer les erreurs de codage courantes en privilégiant la simplicité et la rigueur :

### 1. Penser avant de coder (Think Before Coding)
- **Ne pas assumer, ne pas cacher la confusion, expliciter les compromis.**
- Avant d'implémenter :
  - Déclarez vos hypothèses de manière explicite. En cas d'incertitude, demandez.
  - S'il existe plusieurs interprétations, présentez-les — ne choisissez pas en silence.
  - Si une approche plus simple existe, proposez-la. Argumentez contre la complexité inutile si nécessaire.
  - Si quelque chose n'est pas clair, arrêtez-vous. Nommez ce qui vous perturbe et demandez confirmation.

### 2. La simplicité d'abord (Simplicity First)
- **Le minimum de code nécessaire pour résoudre le problème. Rien de spéculatif.**
- Pas de fonctionnalités au-delà de ce qui est explicitement demandé.
- Pas d'abstractions pour du code à usage unique.
- Pas de "flexibilité" ou de "configurabilité" non requise.
- Pas de gestion d'erreurs pour des scénarios impossibles.
- Si vous écrivez 200 lignes alors que 50 suffiraient, réécrivez-le.
- Posez-vous toujours la question : "Est-ce qu'un développeur senior validerait cette implémentation comme simple et directe ?"

## Phases éliminatoires vs poules

### Détection automatique
Si le champ `competition` contient (insensible à la casse) l'un de ces
termes : `finale`, `1/2`, `demi-finale`, `demi-fin`, `quart`, `play-off`, `playoff`, `coupe`, `barrage`, `promotion`
→ **Phase éliminatoire** 🏆
Sinon (Phase 1, Phase 2, Phase 3…) → **Phase de poule** 📊

### Règles de formulation
- Phase éliminatoire : toujours mentionner explicitement le contexte
  (ex : "ce match est une demi-finale départementale")
- Ne JAMAIS rattacher un match éliminatoire au bilan de phase de poule

### État d'une phase (terminée vs en cours)
`phase_courante` dans `ffbb_bilan` = **dernière phase connue**, pas
nécessairement une phase active.

Règle de temps verbal :
- Si aucun match futur détectable dans la poule → utiliser le **passé**
  ("ont terminé", "ont fini", "se sont classés")
- Si des matchs restent à jouer → utiliser le **présent**
  ("sont", "occupent", "se trouvent")

⚠️ INTERDIT : écrire "sont actuellement Xe" si la phase est terminée.

### Format enrichi pour tout match affiché
- 📍 Domicile / Extérieur
- 🏆 Phase éliminatoire OU 📊 Phase de poule (numéro)
- ⚠️ Si `salle` ou `ville` vides → écrire "Salle non encore renseignée"
- 📍 Format d'adresse standardisé : `[Nom de la Salle] - [Adresse Postale], [Ville]` (gérer proprement les valeurs manquantes sans séparateurs orphelins)

## Développement MCP (FastMCP)
- Cycle de vie : `mcp.run()` ou `mcp.run_streamable_http_async()` — pas de montage manuel via `app.mount()`
- Chemin personnalisé : configurer `mcp.settings.streamable_http_path` avant `mcp.run()`
- Routes HTTP : définies dans `routes.py` via `register_routes(mcp)`
- Tools MCP : définis dans `server.py` via `@mcp.tool()`

## Architecture
```
{NL.join(arch_lines)}
```

## Conventions de code
- Services : `ffbb_<nom>_service` (dans services/)
- Tools MCP : `ffbb_<nom>` (dans server.py, `@mcp.tool()`)
- Pas de suffixe `_compact_` ou `_impl_` exposé
- Modifier une fonction à la fois, seulement si test/usage échoue
- Nouvelle fonction → test manuel validé avant exposition MCP
- **Modularisation** : Le package `services/` (total ≈{services_lines} lignes) remplace l'ancien fichier unique de 2915 lignes pour une meilleure cohésion.

## Commandes
- Démarrer le serveur MCP (stdio) : `rtk uv run python -m ffbb_mcp` (recommandé pour Claude Desktop)
- Démarrer le serveur MCP (HTTP/SSE) : `MCP_MODE=streamable-http rtk uv run python -m ffbb_mcp` (port `9123` par défaut)
- Inspecter/Tester localement : `rtk npx -y @modelcontextprotocol/inspector uv run python -m ffbb_mcp`
- Tests unitaires : `.venv/bin/python -m pytest -q` (pas `pytest` seul)
- Pre-merge :
  1. pytest -q → 0 failed
  2. Test manuel du service : status='ok'
  3. `grep "compact\\|fantôme" src/ffbb_mcp/*.py` → 0 résultat

## Push / Tag / Release Gate
⚠️ OBLIGATION STRICTE : Toutes ces commandes DOIVENT être préfixées par 'rtk' dans le terminal (ex: 'rtk uv run pytest'). Ne jamais exécuter de commande nue sans 'rtk'.
Avant push/tag/release :
- `rtk uv run python tools/check_version_alignment.py`
- `rtk uv run ruff format --check .`
- `rtk uv run ruff check .`
- `rtk uv run mypy src`
- `rtk uv run pytest`
- Si version files modifiés : `rtk uv run tools/sync_version.py` + vérifier diff docs/website
- Vérifier cache (`src/ffbb_mcp/acronyms_cache.json`) — revert impératif de toute modification non liée à votre tâche
- Après push : inspecter les GitHub Actions

## Variables d'environnement
| Variable | Défaut | Usage |
|----------|--------|-------|
{NL.join(env_table_rows)}

## Notes workflow / outils

### PR Comments pour Jules (Google)
- **NE PAS utiliser** `gh pr review --comment` — Jules ne le détecte pas
- **Utiliser** `gh pr comment <number> --body "..."` ou commenter via l'UI GitHub
- Jules écoute les `issue_comment` events, pas les `pull_request_review` events
"""
    return content


def main():
    """Génère AGENTS.md et retourne 0 si le fichier a changé, 1 sinon."""
    # Détecter les variables d'environnement manquantes dans la description
    env_vars = extract_env_vars()
    missing_desc = [
        ev["name"]
        for ev in env_vars
        if ev["name"] not in ENV_DESCRIPTIONS
        and not ev["name"].startswith("FFBB_CACHE_TTL_")
    ]
    if missing_desc:
        print(
            f"⚠️ ATTENTION : Les variables d'environnement suivantes ont été détectées dans le code mais ne sont pas documentées dans ENV_DESCRIPTIONS de update_agents_md.py : {', '.join(missing_desc)}",
            file=sys.stderr,
        )

    new_content = generate_agents_md()
    existing = AGENTS_MD.read_text() if AGENTS_MD.exists() else ""

    if new_content == existing:
        print("AGENTS.md — aucun changement détecté.")
        return 0

    AGENTS_MD.write_text(new_content)
    print("AGENTS.md — mis à jour avec succès.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
