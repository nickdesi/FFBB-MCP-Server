import os
from unittest.mock import patch

from ffbb_mcp.services import _read_positive_int_env, get_cache_ttls


def test_read_positive_int_env():
    # Test valid positive integer
    with patch.dict(os.environ, {"TEST_TTL": "100"}):
        assert _read_positive_int_env("TEST_TTL", 10) == 100

    # Test missing env var
    with patch.dict(os.environ, {}, clear=True):
        assert _read_positive_int_env("TEST_TTL", 10) == 10

    # Test invalid string
    with patch.dict(os.environ, {"TEST_TTL": "abc"}):
        assert _read_positive_int_env("TEST_TTL", 10) == 10

    # Test negative integer
    with patch.dict(os.environ, {"TEST_TTL": "-5"}):
        assert _read_positive_int_env("TEST_TTL", 10) == 10

    # Test zero
    with patch.dict(os.environ, {"TEST_TTL": "0"}):
        assert _read_positive_int_env("TEST_TTL", 10) == 10


def test_get_cache_ttls_structure():
    ttls = get_cache_ttls()
    expected_keys = {"lives", "search", "detail", "calendrier", "bilan", "poule"}
    assert set(ttls.keys()) == expected_keys
    for val in ttls.values():
        assert isinstance(val, int)


@patch("ffbb_mcp.services.get_static_ttl")
def test_get_cache_ttls_bilan_override(mock_get_static):
    mock_get_static.return_value = 1800

    # With override
    # This is expected to fail currently because get_cache_ttls uses get_static_ttl("bilan")
    # directly for the "bilan" key without checking FFBB_CACHE_TTL_BILAN.
    with patch.dict(os.environ, {"FFBB_CACHE_TTL_BILAN": "3600"}):
        ttls = get_cache_ttls()
        assert ttls["bilan"] == 3600


@patch("ffbb_mcp.services.get_static_ttl")
def test_get_cache_ttls_lives_report(mock_get_static):
    # This just ensures we are reporting what's in the cache object for lives
    from ffbb_mcp._state import state

    ttls = get_cache_ttls()
    assert ttls["lives"] == (int(state.cache_lives.ttl) if state.cache_lives else 0)
