"""Bunny Shield Proof-of-Work (Argon2id) Solver & Diagnostic Tool.

Ce module implémente la résolution algorithmique du challenge WAF BunnyCDN (Pullzone 4882605)
déployé sur competitions.ffbb.com (errorcode 112).
"""

from __future__ import annotations


def solve_bunny_pow(
    data_pow: str,
    diff: int = 13,
    max_iterations: int = 200_000,
) -> tuple[str, int]:
    """Résout le défi Argon2id Bunny Shield à partir de l'attribut data-pow.

    Format data-pow: "userkey#challenge"
    Retourne: (response_token, nonce_trouve)
    """
    try:
        from argon2 import low_level
    except ImportError as err:
        raise ImportError(
            "Le package 'argon2-cffi' est requis pour résoudre le PoW Bunny Shield."
        ) from err

    parts = data_pow.split("#")
    if len(parts) < 2:
        raise ValueError(f"Format data-pow invalide: {data_pow}")

    userkey, challenge = parts[0], parts[1]
    diff_str_len = diff // 8
    diff_string = "0" * diff_str_len
    mask = 0xFF >> (((diff_str_len + 1) * 8) - diff)

    found_nonce: int | None = None
    userkey_bytes = userkey.encode("utf-8")

    for nonce in range(max_iterations):
        secret = (challenge + str(nonce)).encode("utf-8")
        raw_hash = low_level.hash_secret_raw(
            secret=secret,
            salt=userkey_bytes,
            time_cost=2,
            memory_cost=512,
            parallelism=1,
            hash_len=32,
            type=low_level.Type.ID,
        )
        hex_hash = raw_hash.hex()
        if (
            hex_hash.startswith(diff_string)
            and (int(hex_hash[diff_str_len], 16) & mask) == 0
        ):
            found_nonce = nonce
            break

    if found_nonce is None:
        raise RuntimeError(
            f"Échec de résolution du PoW Bunny Shield après {max_iterations} itérations."
        )

    response_token = f"{data_pow}#{found_nonce}"
    return response_token, found_nonce
