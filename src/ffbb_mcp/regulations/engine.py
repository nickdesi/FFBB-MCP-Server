"""Moteur de recherche et d'interrogation FTS5 pour les règlements FFBB."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from .indexer import index_manifest
from .models import RegulationArticle, RegulationSearchResult

logger = logging.getLogger(__name__)


def find_default_manifest_path() -> Path | None:
    """Recherche le fichier manifest.yaml des règlements selon plusieurs emplacements ordonnés."""
    # 1. Variable d'environnement explicite
    if env_manifest := os.environ.get("FFBB_REGULATIONS_MANIFEST"):
        p = Path(env_manifest)
        if p.exists():
            return p

    # 2. Données embarquées dans le package (src/ffbb_mcp/regulations/data/manifest.yaml)
    pkg_manifest = Path(__file__).parent / "data" / "manifest.yaml"
    if pkg_manifest.exists():
        return pkg_manifest

    # 3. Répertoire de données spécifié par variable d'environnement
    if data_dir := os.environ.get("FFBB_DATA_DIR"):
        p = Path(data_dir) / "regulations" / "manifest.yaml"
        if p.exists():
            return p

    # 4. Emplacement standard Docker (/app/data/regulations/manifest.yaml)
    docker_manifest = Path("/app/data/regulations/manifest.yaml")
    if docker_manifest.exists():
        return docker_manifest

    # 5. Racine du dépôt Git en environnement de dev
    try:
        repo_manifest = (
            Path(__file__).resolve().parents[3]
            / "data"
            / "regulations"
            / "manifest.yaml"
        )
        if repo_manifest.exists():
            return repo_manifest
    except IndexError:
        pass

    return None


def _sanitize_fts5_query(raw_query: str) -> str:
    """Nettoie et formate la requête utilisateur pour SQLite FTS5."""
    # Remplacer les caractères spéciaux FTS5
    cleaned = re.sub(r"[^\w\s\-\.\']+", " ", raw_query, flags=re.UNICODE)
    terms = [t.strip() for t in cleaned.split() if len(t.strip()) > 1]
    if not terms:
        return ""
    # Construction d'une requête combinant préfixes et correspondance exacte
    fts_terms = []
    for term in terms:
        if term.startswith("-"):
            continue
        fts_terms.append(f'"{term}"*')
    return " OR ".join(fts_terms)


class RegulationsEngine:
    """Moteur d'accès et de recherche dans les règlements sportifs."""

    def __init__(self, db_path: Path | None = None, manifest_path: Path | None = None):
        self.db_path = db_path
        self.manifest_path = manifest_path or find_default_manifest_path()
        self._conn: sqlite3.Connection | None = None
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Initialise la connexion SQLite, garantit le schéma et indexe le corpus si nécessaire."""
        if self._conn is not None:
            return

        from .indexer import init_sqlite_schema

        if self.db_path:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # Toujours initialiser les tables (regulation_articles, regulations_fts) pour parer aux 'no such table'
        init_sqlite_schema(self._conn)

        # Vérifier si la table contient déjà des articles. Si vide et qu'un manifeste existe, indexer.
        needs_indexing = False
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM regulation_articles")
            row = cursor.fetchone()
            if row and row[0] == 0:
                needs_indexing = True
        except Exception:
            needs_indexing = True

        if needs_indexing and self.manifest_path and self.manifest_path.exists():
            try:
                indexed = index_manifest(self.manifest_path, conn=self._conn)
                logger.info(
                    "Manifeste règlements indexé : %s articles chargés.", indexed
                )
            except Exception as e:
                logger.error(
                    "Erreur lors de l'indexation du manifeste de règlements : %s", e
                )

    def search(
        self,
        query: str,
        season: str = "2026-2027",
        level: str | None = None,
        organizer: str | None = None,
        category: str | None = None,
        topic: str | None = None,
        limit: int = 5,
    ) -> list[RegulationSearchResult]:
        """Recherche plein texte avec filtres à facettes et scoring BM25."""
        if not self._conn:
            return []

        fts_query = _sanitize_fts5_query(query)
        cursor = self._conn.cursor()

        # Si la requête texte est vide mais qu'on a des filtres, on liste les articles correspondants
        if not fts_query:
            sql = """
            SELECT id, document_id, season, level, organizer, categories,
                   article_number, article_title, content, topics, source_url
            FROM regulation_articles
            WHERE season = ?
            """
            params: list[Any] = [season]
            if level:
                sql += " AND level = ?"
                params.append(level)
            if organizer:
                sql += " AND organizer LIKE ?"
                params.append(f"%{organizer}%")
            if category:
                sql += " AND categories LIKE ?"
                params.append(f"%{category}%")
            if topic:
                sql += " AND topics LIKE ?"
                params.append(f"%{topic}%")
            sql += " LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            rows = cursor.fetchall()
            results = []
            for row in rows:
                art = RegulationArticle(
                    id=row["id"],
                    document_id=row["document_id"],
                    season=row["season"],
                    level=row["level"],
                    organizer=row["organizer"],
                    categories=json.loads(row["categories"])
                    if row["categories"]
                    else [],
                    article_number=row["article_number"],
                    article_title=row["article_title"],
                    content=row["content"],
                    topics=row["topics"].split(",") if row["topics"] else [],
                    source_url=row["source_url"],
                )
                results.append(RegulationSearchResult(article=art, score=1.0))
            return results

        # Requête FTS5 avec scoring BM25
        sql = """
        SELECT a.id, a.document_id, a.season, a.level, a.organizer, a.categories,
               a.article_number, a.article_title, a.content, a.topics, a.source_url,
               bm25(regulations_fts) as rank
        FROM regulations_fts f
        JOIN regulation_articles a ON f.rowid = a.rowid
        WHERE regulations_fts MATCH ?
          AND a.season = ?
        """
        params = [fts_query, season]

        if level:
            sql += " AND a.level = ?"
            params.append(level)
        if organizer:
            sql += " AND a.organizer LIKE ?"
            params.append(f"%{organizer}%")
        if category:
            sql += " AND a.categories LIKE ?"
            params.append(f"%{category}%")
        if topic:
            sql += " AND a.topics LIKE ?"
            params.append(f"%{topic}%")

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.error(f"Erreur SQL FTS5: {e} pour query='{fts_query}'")
            return []

        results = []
        for row in rows:
            art = RegulationArticle(
                id=row["id"],
                document_id=row["document_id"],
                season=row["season"],
                level=row["level"],
                organizer=row["organizer"],
                categories=json.loads(row["categories"]) if row["categories"] else [],
                article_number=row["article_number"],
                article_title=row["article_title"],
                content=row["content"],
                topics=row["topics"].split(",") if row["topics"] else [],
                source_url=row["source_url"],
            )
            # FTS5 bm25 renvoie un score négatif (plus petit = plus pertinent)
            score = round(abs(float(row["rank"])), 2)
            results.append(RegulationSearchResult(article=art, score=score))

        # Fallback fédéral automatique : si une recherche filtrée sur un organisateur local
        # ne renvoie rien, on relance la recherche au niveau fédéral car le RSG FFBB
        # s'applique universellement à tous les comités et ligues de France.
        if not results and organizer and level != "federal":
            logger.info(
                f"Aucun résultat spécifique pour organizer='{organizer}'. Fallback sur le RSG fédéral FFBB."
            )
            return self.search(
                query=query,
                season=season,
                level="federal",
                category=category,
                topic=topic,
                limit=limit,
            )

        return results

    def list_available_documents(
        self, season: str = "2026-2027"
    ) -> list[dict[str, Any]]:
        """Liste l'ensemble des règlements et juridictions actuellement indexés."""
        if not self._conn:
            return []

        cursor = self._conn.cursor()
        sql = """
        SELECT document_id, season, level, organizer,
               COUNT(*) as total_articles,
               MIN(source_url) as source_url
        FROM regulation_articles
        WHERE season = ?
        GROUP BY document_id, season, level, organizer
        ORDER BY
            CASE level
                WHEN 'federal' THEN 1
                WHEN 'regional' THEN 2
                WHEN 'departmental' THEN 3
                ELSE 4
            END, organizer
        """
        try:
            cursor.execute(sql, (season,))
            rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.error(f"Erreur SQL list_available_documents: {e}")
            return []
        return [
            {
                "document_id": r["document_id"],
                "season": r["season"],
                "level": r["level"],
                "organizer": r["organizer"],
                "total_articles": r["total_articles"],
                "source_url": r["source_url"],
            }
            for r in rows
        ]

    def get_article(
        self,
        document_id: str | None = None,
        article_number: str | None = None,
        organizer: str | None = None,
        season: str = "2026-2027",
    ) -> RegulationArticle | None:
        """Récupère un article exact par numéro et document/organisateur."""
        if not self._conn:
            return None

        cursor = self._conn.cursor()
        sql = """
        SELECT id, document_id, season, level, organizer, categories,
               article_number, article_title, content, topics, source_url
        FROM regulation_articles
        WHERE season = ?
        """
        params: list[Any] = [season]

        if document_id:
            sql += " AND document_id = ?"
            params.append(document_id)
        if organizer:
            sql += " AND organizer LIKE ?"
            params.append(f"%{organizer}%")
        if article_number:
            # Accepter "28", "Article 28", "art. 28", etc.
            num_clean = re.sub(r"[^\w\.]+", "", article_number).lower()
            sql += " AND (LOWER(REPLACE(article_number, ' ', '')) LIKE ? OR article_number LIKE ?)"
            params.append(f"%{num_clean}%")
            params.append(f"%{article_number}%")

        sql += " LIMIT 1"
        try:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        except sqlite3.OperationalError as e:
            logger.error(f"Erreur SQL get_article: {e}")
            return None
        if not row:
            return None

        return RegulationArticle(
            id=row["id"],
            document_id=row["document_id"],
            season=row["season"],
            level=row["level"],
            organizer=row["organizer"],
            categories=json.loads(row["categories"]) if row["categories"] else [],
            article_number=row["article_number"],
            article_title=row["article_title"],
            content=row["content"],
            topics=row["topics"].split(",") if row["topics"] else [],
            source_url=row["source_url"],
        )

    def close(self) -> None:
        """Ferme la connexion SQLite sous-jacente."""
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()


# Singleton d'instance partagée
_DEFAULT_ENGINE: RegulationsEngine | None = None


def get_regulations_engine() -> RegulationsEngine:
    """Retourne ou initialise l'instance partagée du moteur de règlements."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = RegulationsEngine()
    return _DEFAULT_ENGINE
