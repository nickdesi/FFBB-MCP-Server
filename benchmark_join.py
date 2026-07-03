import time
import os

def test_generator():
    t0 = time.time()
    for _ in range(1000000):
        parts = ["123", "Main St", "City"]
        address = " ".join(str(part).strip() for part in parts if part)
    t1 = time.time()
    print(f"generator: {t1 - t0:.4f}s")

def test_listcomp():
    t0 = time.time()
    for _ in range(1000000):
        parts = ["123", "Main St", "City"]
        address = " ".join([str(part).strip() for part in parts if part])
    t1 = time.time()
    print(f"listcomp: {t1 - t0:.4f}s")

test_generator()
test_listcomp()
