## 2024-05-24 - Optimisation de la normalisation des noms d'équipes
**Learning:** L'optimisation apparente de `_normalize_name` via l'encodage ASCII (`s.encode("ascii", "ignore").decode("utf-8")`) en remplacement du filtrage des catégories Unicode (`"".join(ch for ch in s if unicodedata.category(ch) != "Mn")`) est certes plus rapide, mais introduit un risque de bug subtil avec certains caractères français spécifiques (comme "Œ", "Æ"). Le filtrage par catégorie Unicode est plus sûr dans le contexte de noms français, même s'il est plus lent. La véritable optimisation réside dans la réduction des appels redondants via le "hoisting" (pré-calcul) plutôt que la micro-optimisation de la fonction elle-même.
**Action:** Toujours évaluer les risques fonctionnels des optimisations de manipulation de chaînes liées à l'Unicode (spécifiquement dans un contexte francophone). Privilégier le hoisting des opérations coûteuses en dehors des boucles avant de tenter de réécrire la logique interne des fonctions.

## 2024-05-18 - [JSON Serialization Performance]
**Learning:** In heavily recursive JSON serialization functions (like `serialize_model`), calling `hasattr()` on native collections (dicts, lists) introduces significant overhead because `hasattr` internally handles `AttributeError` exceptions when the attribute doesn't exist. Python's internal exception handling is relatively slow.
**Action:** Always place `isinstance(obj, dict)` and `isinstance(obj, list)` checks BEFORE `hasattr` checks when traversing standard data structures. Also, when checking for primitives, prefer `isinstance(obj, str | int | float | bool)` over strict `type(obj) in (...)` to ensure data integrity for subclasses (like `IntEnum`), even if strict type checking is marginally faster.

## 2026-04-18 - [API Payload inconsistencies]
**Learning:** The FFBB API response structure can be inconsistent. In the `engagements` list fetched for a club, the `nom` attribute may unexpectedly be `None` for some teams. Logic strictly relying on string parsing of `nom` will fail silently or filter out valid results.
**Action:** Always rely on structured fields like `numero_equipe` primarily, and use string parsing only as a fallback. Ensure that `None` values are safely handled by using `.get("key", "")` before attempting string operations.

## 2024-05-25 - [Type Checking Optimization for Serialization]
**Learning:** `type(obj) is ...` is measurably faster than `isinstance(obj, ...)` in Python because it avoids traversing the Method Resolution Order (MRO) for inheritance. In heavily recursive serialization functions (like `serialize_model`), introducing a "fast path" with exact type checks for standard JSON primitives (`str`, `int`, `float`, `bool`, `dict`, `list`) can yield a significant ~3x speedup.
**Action:** Use `type(obj) is ...` fast paths in critical data transformation/serialization functions to handle standard data types, while retaining `isinstance` as a fallback to ensure support for sub-classes (like `IntEnum` or custom collections).
## 2025-04-19 - [CI Troubleshooting]
**Learning:** Duplicate arguments defined in pytest CLI vs pytest config (e.g. `--cov=ffbb_mcp`) can cause fatal test failures in newer pytest versions when invoked via CI. Furthermore, CI actions must be updated to existing major versions (e.g., `actions/checkout@v6` -> `v4`).
**Action:** Always verify action versions and pytest argument combinations locally before pushing.

## 2024-04-20 - [Performance] Regex compilation overhead in cache miss scenarios
**Learning:** In highly cached functions (like `parse_categorie` decorated with `lru_cache`), the overhead of dynamically compiling regular expressions using `re.search()` with string literals dominates the execution time during cache misses. This becomes relevant when the cache is small compared to the input space, or when handling cold-start requests. Python's internal regex caching limits its effectiveness in complex or varied patterns.
**Action:** Always pre-compile regular expressions at the module level using `re.compile()` for functions that will be called frequently, even if they are memoized. This halved the uncached execution time of string parsing logic in this codebase.
