import timeit
from functools import lru_cache

@lru_cache(maxsize=512)
def norm_cached(value: str):
    return value.upper()

def test_cache():
    return norm_cached("hello")

def test_no_cache(value: str):
    return value

value = norm_cached("hello")
print("cache hit: ", timeit.timeit('test_cache()', globals=globals(), number=1000000))
print("pass var:  ", timeit.timeit('test_no_cache(value)', globals=globals(), number=1000000))
