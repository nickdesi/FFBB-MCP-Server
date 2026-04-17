import timeit
import unicodedata
from functools import lru_cache

@lru_cache(maxsize=512)
def norm_cached_join(value: str):
    if not value:
        return ""
    s = value.strip().upper()
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

@lru_cache(maxsize=512)
def norm_cached_encode(value: str):
    if not value:
        return ""
    s = value.strip().upper()
    s = unicodedata.normalize("NFD", s)
    return s.encode("ascii", "ignore").decode("utf-8")

def test_cache_join():
    return norm_cached_join("JEANNE D'ARC DE VICHY - ÉQUIPE 1")

def test_cache_encode():
    return norm_cached_encode("JEANNE D'ARC DE VICHY - ÉQUIPE 1")

print("cache join:   ", timeit.timeit('test_cache_join()', globals=globals(), number=1000000))
print("cache encode: ", timeit.timeit('test_cache_encode()', globals=globals(), number=1000000))

print("join diff arg:  ", timeit.timeit('norm_cached_join(str(i))', setup='i=0', globals=globals(), number=100000))
print("encode diff arg:", timeit.timeit('norm_cached_encode(str(i))', setup='i=0', globals=globals(), number=100000))
