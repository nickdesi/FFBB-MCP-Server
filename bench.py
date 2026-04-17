import timeit
import unicodedata

def norm_join(value: str):
    s = value.strip().upper()
    s = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")

def norm_encode(value: str):
    s = value.strip().upper()
    s = unicodedata.normalize("NFD", s)
    return s.encode("ascii", "ignore").decode("utf-8")

print("join: ", timeit.timeit('norm_join("JEANNE D\'ARC DE VICHY - ÉQUIPE 1")', globals=globals(), number=100000))
print("encode: ", timeit.timeit('norm_encode("JEANNE D\'ARC DE VICHY - ÉQUIPE 1")', globals=globals(), number=100000))
