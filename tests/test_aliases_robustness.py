"""Tests unitaires de robustesse pour la gestion des alias et acronymes (aliases.py)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ffbb_mcp.aliases import (
    _load_acronyms_cache,
    _save_acronyms_cache,
    enrich_acronym_cache,
    normalize_query,
    resolve_acronym,
)


@pytest.fixture
def temp_cache_file(tmp_path):
    """Fixture qui fournit un chemin de fichier cache temporaire et isole l'état global."""
    test_file = tmp_path / "test_acronyms_cache.json"

    # Réinitialisation de l'état global avant le test
    with (
        patch("ffbb_mcp.aliases._CACHE_FILE", test_file),
        patch("ffbb_mcp.aliases._acronyms_cache", None),
        patch("ffbb_mcp.aliases._acronyms_cache_upper", None),
    ):
        yield test_file


def test_load_cache_default_when_missing(temp_cache_file):
    """Vérifie que le cache est initialisé avec les valeurs par défaut si le fichier n'existe pas."""
    assert not temp_cache_file.exists()

    cache = _load_acronyms_cache()

    assert cache is not None
    assert "ASVEL" in cache
    assert cache["ASVEL"] == "Villeurbanne"
    assert temp_cache_file.exists()  # Doit être sauvegardé automatiquement


def test_load_cache_from_existing_file(temp_cache_file):
    """Vérifie que le cache est correctement chargé depuis un fichier JSON existant."""
    custom_data = {"TEST": "Club de Test Basketball"}
    temp_cache_file.write_text(json.dumps(custom_data), encoding="utf-8")

    cache = _load_acronyms_cache()

    assert cache == custom_data
    assert resolve_acronym("TEST") == "Club de Test Basketball"


def test_load_cache_corrupted_json_fallback(temp_cache_file):
    """Vérifie que le cache retombe sur ses valeurs par défaut si le JSON est corrompu."""
    temp_cache_file.write_text("{invalid json...", encoding="utf-8")

    # Doit journaliser un warning mais ne pas planter et charger les valeurs par défaut
    with patch("ffbb_mcp.aliases.logger.warning") as mock_warning:
        cache = _load_acronyms_cache()
        assert "ASVEL" in cache
        assert mock_warning.call_count >= 1


def test_save_cache_os_error_handling(temp_cache_file):
    """Vérifie que les erreurs système (ex: permission refusée) lors de l'écriture sont gérées proprement."""
    _load_acronyms_cache()  # Initialise le cache

    # Mock mkdir pour qu'il lève une OSError
    with (
        patch.object(Path, "mkdir", side_effect=OSError("Permission denied")),
        patch("ffbb_mcp.aliases.logger.warning") as mock_warning,
    ):
        _save_acronyms_cache()
        assert mock_warning.call_count >= 1
        assert "Permission denied" in str(mock_warning.call_args[0][2])


def test_enrich_acronym_cache_and_save(temp_cache_file):
    """Vérifie que l'auto-enrichissement extrait correctement les initiales et met à jour le fichier cache."""
    _load_acronyms_cache()

    # Enrichir avec un nouveau club
    enrich_acronym_cache("Union Stadium Clermontois")

    # USC doit être généré à partir de Union Stadium Clermontois
    assert resolve_acronym("USC") == "Union Stadium Clermontois"

    # Vérifier que c'est bien écrit sur le disque
    saved_data = json.loads(temp_cache_file.read_text(encoding="utf-8"))
    assert saved_data["USC"] == "Union Stadium Clermontois"


def test_enrich_acronym_cache_ignores_existing(temp_cache_file):
    """Vérifie que l'enrichissement ignore un acronyme s'il est déjà enregistré (case-insensitive)."""
    _load_acronyms_cache()

    # ASVEL est déjà présent par défaut ("Villeurbanne")
    # Tenter de l'enrichir avec un autre nom ne doit rien changer
    enrich_acronym_cache("Association Sportive de Villeurbanne Et Lyon")

    assert resolve_acronym("ASVEL") == "Villeurbanne"


def test_resolve_acronym_invalid_cases(temp_cache_file):
    """Vérifie que resolve_acronym ignore les requêtes invalides ou non éligibles."""
    _load_acronyms_cache()

    # Longueur trop grande (>= 7)
    assert resolve_acronym("ASVELXXX") == "ASVELXXX"

    # Caractères minuscules ou spéciaux
    assert resolve_acronym("Asvel") == "Asvel"
    assert resolve_acronym("AS123") == "AS123"
    assert resolve_acronym("") == ""


def test_normalize_query_integration(temp_cache_file):
    """Vérifie l'intégration globale de la normalisation avec le cache d'acronymes temporaire."""
    _load_acronyms_cache()
    enrich_acronym_cache("Basket Club Gerzatois")

    # Résolution d'acronyme auto-enrichi
    assert normalize_query("BCG") == "Basket Club Gerzatois"

    # Résolution d'alias statique
    assert normalize_query("ldlc asvel") == "lyon villeurbanne"
