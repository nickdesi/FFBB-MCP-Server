import time
import re
import sys
import unicodedata

text = "A test string with some digits 123"

def test_manual():
    t0 = time.time()
    for _ in range(1000000):
        any(c.isdigit() for c in text)
    t1 = time.time()
    print(f"manual generator: {t1 - t0:.4f}s")

    t0 = time.time()
    for _ in range(1000000):
        any([c.isdigit() for c in text])
    t1 = time.time()
    print(f"manual listcomp: {t1 - t0:.4f}s")

_digit_pattern = re.compile(r"\d")
def test_regex():
    t0 = time.time()
    for _ in range(1000000):
        _digit_pattern.search(text)
    t1 = time.time()
    print(f"regex: {t1 - t0:.4f}s")

test_manual()
test_regex()
