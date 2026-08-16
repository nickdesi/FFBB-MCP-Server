## 2025-02-28 - Avoid Over-Optimizing Built-in String Operations
**Learning:** Adding a literal fast-path check like `if " " not in query:` before running `.split(None, 1)` yields only a nanosecond-level improvement and introduces edge cases (e.g., breaking splits on tabs or non-breaking spaces).
**Action:** Do not attempt to bypass single, native C-optimized Python string methods (like `.split()`) with Python-level literal checks, as the performance gain is an unmeasurable micro-optimization and risks functional regressions.

## 2025-02-28 - Fast Path Subclass Checking vs Exact Matching
**Learning:** Replacing `isinstance(obj, dict)` with `type(obj) is dict` provides a minor speedup but breaks compatibility with subclasses (e.g., `OrderedDict`). In robust library code handling general payloads, standardizing on exact primitives may silently bypass necessary subclass pruning.
**Action:** Avoid replacing `isinstance()` with `type() is` in public-facing generic utility functions (like `prune_payload`) unless profiling explicitly proves it is a major bottleneck *and* the payload type constraints are strictly controlled and known.
