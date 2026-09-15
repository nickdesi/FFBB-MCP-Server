"""Parseur et indexeur des règlements FFBB en base SQLite FTS5."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path


from .models import DocumentManifestEntry, RegulationArticle, RegulationsManifest

logger = logging.getLogger(__name__)

ARTICLE_HEADER_PATTERN = re.compile(
    r"^(?:#|##)\s*(Article\s+[\w\.\-]+(?:\s*-\s*[^\n]+)?|Section\s+[\w\.\-]+(?:\s*-\s*[^\n]+)?|Annexe\s+[\w\.\-]+(?:\s*-\s*[^\n]+)?)",
    re.IGNORECASE | re.MULTILINE,
)


def parse_markdown_document(
    file_path: Path,
    manifest_entry: DocumentManifestEntry,
    season: str,
) -> list[RegulationArticle]:
    """Parse un fichier Markdown de règlement découpé par articles."""
    if not file_path.exists():
        logger.warning(f"Fichier de règlement introuvable : {file_path}")
        return []

    raw_text = file_path.read_text(encoding="utf-8")
    frontmatter: dict[str, Any] = {}
    content_text = raw_text

    # Extraction du frontmatter YAML si présent
    if raw_text.startswith("---"):
        parts = raw_text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                content_text = parts[2]
            except Exception as e:
                logger.error(f"Erreur parsing frontmatter dans {file_path}: {e}")

    # Récupération des métadonnées fusionnées
    doc_id = frontmatter.get("id", manifest_entry.id)
    doc_season = frontmatter.get("season", season)
    doc_level = frontmatter.get("level", manifest_entry.level)
    doc_organizer = frontmatter.get("organizer", manifest_entry.organizer)
    doc_categories = frontmatter.get("categories", manifest_entry.categories)
    doc_topics = frontmatter.get("topics", manifest_entry.topics)
    doc_source_url = frontmatter.get("source_url", manifest_entry.source_url)

    # Découpage par Article / Titre
    articles: list[RegulationArticle] = []

    # Trouver tous les en-têtes d'articles
    matches = list(ARTICLE_HEADER_PATTERN.finditer(content_text))
    if not matches:
        # Si aucun en-tête d'article spécifique n'est trouvé, traiter le document entier comme un seul article
        clean_content = content_text.strip()
        if clean_content:
            art = RegulationArticle(
                id=f"{doc_id}_general",
                document_id=doc_id,
                season=doc_season,
                level=doc_level,
                organizer=doc_organizer,
                categories=doc_categories,
                article_number="Général",
                article_title=manifest_entry.title,
                content=clean_content,
                topics=doc_topics,
                source_url=doc_source_url,
            )
            articles.append(art)
        return articles

    for i, match in enumerate(matches):
        header_raw = match.group(1).strip()
        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(content_text)

        body = content_text[start_pos:end_pos].strip()

        # Séparer le numéro et le titre (ex: "Article 28 - Classement et départage")
        if " - " in header_raw:
            parts = header_raw.split(" - ", 1)
            art_num = parts[0].strip()
            art_title = parts[1].strip()
        else:
            art_num = header_raw
            art_title = f"{header_raw} - {manifest_entry.title}"

        # Création de l'ID unique
        safe_num = re.sub(r"[^\w]+", "_", art_num.lower()).strip("_")
        art_id = f"{doc_id}_{safe_num}"

        art = RegulationArticle(
            id=art_id,
            document_id=doc_id,
            season=doc_season,
            level=doc_level,
            organizer=doc_organizer,
            categories=doc_categories,
            article_number=art_num,
            article_title=art_title,
            content=f"{art_num} - {art_title}\n\n{body}"
            if body
            else f"{art_num} - {art_title}",
            topics=doc_topics,
            source_url=doc_source_url,
        )
        articles.append(art)

    return articles


def init_sqlite_schema(conn: sqlite3.Connection) -> None:
    """Initialise le schéma SQLite standard et la table FTS5."""
    cursor = conn.cursor()
    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS regulation_articles (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        season TEXT NOT NULL,
        level TEXT NOT NULL,
        organizer TEXT NOT NULL,
        categories TEXT NOT NULL,
        article_number TEXT NOT NULL,
        article_title TEXT NOT NULL,
        content TEXT NOT NULL,
        topics TEXT NOT NULL,
        source_url TEXT
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS regulations_fts USING fts5(
        article_number,
        article_title,
        content,
        topics,
        organizer,
        categories,
        content='regulation_articles',
        content_rowid='rowid',
        tokenize='unicode61 remove_diacritics 1'
    );

    -- Triggers de synchronisation FTS5
    CREATE TRIGGER IF NOT EXISTS reg_ai AFTER INSERT ON regulation_articles BEGIN
        INSERT INTO regulations_fts(rowid, article_number, article_title, content, topics, organizer, categories)
        VALUES (new.rowid, new.article_number, new.article_title, new.content, new.topics, new.organizer, new.categories);
    END;

    CREATE TRIGGER IF NOT EXISTS reg_ad AFTER DELETE ON regulation_articles BEGIN
        INSERT INTO regulations_fts(regulations_fts, rowid, article_number, article_title, content, topics, organizer, categories)
        VALUES ('delete', old.rowid, old.article_number, old.article_title, old.content, old.topics, old.organizer, old.categories);
    END;

    CREATE TRIGGER IF NOT EXISTS reg_au AFTER UPDATE ON regulation_articles BEGIN
        INSERT INTO regulations_fts(regulations_fts, rowid, article_number, article_title, content, topics, organizer, categories)
        VALUES ('delete', old.rowid, old.article_number, old.article_title, old.content, old.topics, old.organizer, old.categories);
        INSERT INTO regulations_fts(rowid, article_number, article_title, content, topics, organizer, categories)
        VALUES (new.rowid, new.article_number, new.article_title, new.content, new.topics, new.organizer, new.categories);
    END;
    """)
    conn.commit()


def index_manifest(
    manifest_path: Path,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Charge le manifeste et indexe tous les documents dans la base SQLite."""
    if not manifest_path.exists():
        logger.warning(f"Manifeste des règlements introuvable : {manifest_path}")
        return 0

    with open(manifest_path, encoding="utf-8") as f:
        manifest_data = yaml.safe_load(f)

    manifest = RegulationsManifest(**manifest_data)
    base_dir = manifest_path.parent / manifest.season

    should_close = False
    if conn is None:
        if db_path is None:
            db_path = manifest_path.parent / "regulations.sqlite"
        conn = sqlite3.connect(db_path)
        should_close = True

    try:
        init_sqlite_schema(conn)
        cursor = conn.cursor()

        total_articles = 0
        for entry in manifest.documents:
            file_path = base_dir / entry.file
            articles = parse_markdown_document(file_path, entry, manifest.season)
            for art in articles:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO regulation_articles (
                        id, document_id, season, level, organizer, categories,
                        article_number, article_title, content, topics, source_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        art.id,
                        art.document_id,
                        art.season,
                        art.level,
                        art.organizer,
                        json.dumps(art.categories, ensure_ascii=False),
                        art.article_number,
                        art.article_title,
                        art.content,
                        ",".join(art.topics),
                        art.source_url,
                    ),
                )
                total_articles += 1

        conn.commit()
        logger.info(
            f"Indexation terminée : {total_articles} articles indexés dans FTS5."
        )
        return total_articles
    finally:
        if should_close and conn:
            conn.close()
