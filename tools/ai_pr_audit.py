#!/usr/bin/env python3
"""
Script d'audit automatique des Pull Requests par IA.
Utilise l'API Gemini gratuite (gemini-2.5-flash) pour analyser le diff d'une PR
et poste un commentaire d'audit constructif sur GitHub.
"""

import json
import os
import subprocess
import urllib.error
import urllib.request


def get_git_diff() -> str:
    """Récupère le diff git par rapport à la branche cible (main)."""
    try:
        # S'assurer que la branche main est disponible localement
        subprocess.run(
            ["git", "fetch", "origin", "main", "--depth=1"],
            check=True,
            capture_output=True,
        )
        # Obtenir le diff
        result = subprocess.run(
            ["git", "diff", "origin/main...HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except Exception as e:
        print(f"⚠️ Impossible de récupérer le diff git : {e}")
        return ""


def call_gemini(api_key: str, diff: str) -> str:
    """Appelle l'API Gemini gratuite avec le diff pour obtenir la revue de code."""
    # Tronquer le diff s'il est gigantesque pour rester dans les limites et garder une revue concise
    max_diff_len = 60000
    if len(diff) > max_diff_len:
        diff = (
            diff[:max_diff_len] + "\n\n[Diff tronqué car trop long pour l'analyse...]"
        )

    prompt = f"""Tu es Antigravity, un expert en développement Python, architecture FastMCP et basketball français.
Analyse le diff de Pull Request ci-dessous et fais une revue de code constructive et rigoureuse.

Ligne de conduite :
- Sois direct, professionnel, constructif et bienveillant.
- Identifie les bugs potentiels, les problèmes de typage statique (mypy), de performance, de sécurité ou de style (Ruff).
- Souligne les points positifs et les bonnes pratiques appliquées.
- Reste concis et synthétique (ne commente pas chaque ligne, focalise-toi sur le plus important).
- Rédige impérativement ta réponse en français, bien mise en forme en Markdown avec des sections claires (ex.: "Points forts 🌟", "Suggestions d'amélioration 🛠️", "Bugs potentiels / Points critiques ⚠️").

Voici le diff de la PR :
```diff
{diff}
```
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048},
    }

    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            text = res_body["candidates"][0]["content"]["parts"][0]["text"]
            return text
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"❌ Erreur HTTP lors de l'appel Gemini : {e.code} - {e.reason}")
        print(f"Détails : {err_body}")
        return ""
    except Exception as e:
        print(f"❌ Erreur inattendue lors de l'appel Gemini : {e}")
        return ""


def post_github_comment(repo: str, pr_number: int, token: str, body: str) -> bool:
    """Poste le commentaire d'audit sur la Pull Request GitHub."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    payload = {
        "body": f"### 🤖 Audit Automatique de la PR par Antigravity\n\n{body}\n\n*Note : Cet audit est généré automatiquement par l'IA via le Free Tier de Gemini. Répondez à ce commentaire ou modifiez votre code pour corriger les points signalés.*"
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15):
            print("✅ Commentaire posté avec succès sur la PR !")
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(
            f"❌ Erreur HTTP lors de la publication sur GitHub : {e.code} - {e.reason}"
        )
        print(f"Détails : {err_body}")
        return False
    except Exception as e:
        print(f"❌ Erreur inattendue lors de la publication sur GitHub : {e}")
        return False


def main():
    print("🚀 Démarrage de l'audit IA de la PR...")

    # 1. Vérification des variables d'environnement
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("⚠️ GEMINI_API_KEY non configurée dans les secrets. Audit ignoré.")
        return

    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        print("❌ GITHUB_TOKEN non configuré. Impossible d'interagir avec GitHub.")
        return

    github_event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not github_event_path or not os.path.exists(github_event_path):
        print(
            "❌ GITHUB_EVENT_PATH introuvable. Ce script doit tourner dans GitHub Actions."
        )
        return

    # 2. Lecture des détails de la PR depuis l'événement GitHub
    with open(github_event_path, encoding="utf-8") as f:
        event_data = json.load(f)

    pr_number = event_data.get("pull_request", {}).get("number")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not pr_number or not repo:
        print("❌ Impossible de déterminer le numéro de PR ou le dépôt.")
        return

    print(f"Analyse de la PR #{pr_number} sur le dépôt {repo}...")

    # 3. Récupération du diff
    diff = get_git_diff()
    if not diff or len(diff.strip()) < 10:
        print("📝 Diff vide ou trop court. Aucun audit nécessaire.")
        return

    print(f"Diff récupéré ({len(diff)} caractères). Appel de l'IA...")

    # 4. Appel de l'API Gemini
    review = call_gemini(gemini_key, diff)
    if not review:
        print("❌ Impossible de générer la revue IA.")
        return

    # 5. Publication du commentaire
    post_github_comment(repo, pr_number, github_token, review)


if __name__ == "__main__":
    main()
