## 2024-05-28 - [Recursive Serialization Optimization in Python]
**Learning:** In heavily recursive data transformation functions like `prune_payload`, avoiding dynamic limits lookups (e.g., `os.environ.get()` cast to `int`) and extracting them to module-level constants yields significant speedups. Furthermore, prioritizing primitives `(str, int, float, bool, None)` as a fast path using `type(obj)` avoids repeatedly falling into slower dict and list comprehension blocks, saving an extra ~5-10% computation time. Attempting to use `@lru_cache` for environment variables is an anti-pattern as the variable might change at runtime or not change at all making a constant significantly faster without overhead.
**Action:** When optimizing recursive tree walking functions handling large JSONs, hoist limits and constants to the module level and prioritize `type(obj) is ...` for primitives at the beginning of the function.

## 2024-05-29 - [Optimization of empty collection filtering in recursive logic]
**Learning:** Checking for empty collections using `v != []` or `v != {}` inside tight recursive loops forces Python to allocate new empty list/dict objects for each comparison, creating significant overhead in functions like `prune_payload`.
**Action:** Use boolean evaluation paired with explicit type checks: `v or (type(v) is not list and type(v) is not dict)` avoids empty list/dict allocations while correctly maintaining falsy primitives like `0`, `False`, or `""`.

## 2024-05-30 - [Optimization of Regex Substitutions in Tight Loops]
**Learning:** In text normalization functions that iterate over a list of regex patterns to apply substitutions, unconditionally executing the regex engine (e.g., `alias_pattern.sub()`) for every pattern is extremely slow. For queries that do not contain the target alias, the regex engine overhead dominates execution time.
**Action:** Always add a fast-path literal substring check (`if alias in text:`) before invoking a complex or word-bounded regex substitution if the presence of the literal substring is a prerequisite for a match. This avoids expensive regex invocations and can yield speedups of 10x-20x for non-matching cases.
