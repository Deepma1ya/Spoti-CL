"""Tests for the configuration and the cache."""

from __future__ import annotations

import time

from spoti_cl.cache import Cache
from spoti_cl.config import Config


def test_config_defaults() -> None:
    config = Config()
    assert config.format == "best"
    assert config.quality == 320
    assert config.threads >= 1


def test_config_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("SPOTICL_FORMAT", "flac")
    monkeypatch.setenv("SPOTICL_QUALITY", "128")
    monkeypatch.setenv("SPOTICL_THREADS", "9")
    config = Config.load()
    assert config.format == "flac"
    assert config.quality == 128
    assert config.threads == 9


def test_config_round_trip(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = Config()
    config.format = "mp3"
    config.save(path)
    assert Config.load(path).format == "mp3"


def test_cache_round_trip(tmp_path) -> None:
    cache = Cache(tmp_path)
    cache.set("thing", {"a": 1})
    assert cache.get("thing") == {"a": 1}
    cache.delete("thing")
    assert cache.get("thing") is None


def test_cache_expires(tmp_path) -> None:
    cache = Cache(tmp_path)
    cache.set("thing", "value", ttl=0.01)
    time.sleep(0.05)
    assert cache.get("thing", ttl=0.01) is None
    # A ttl of -1 means "keep forever".
    cache.set("forever", "value", ttl=-1)
    time.sleep(0.05)
    assert cache.get("forever", ttl=-1) == "value"


def test_cache_survives_a_new_instance(tmp_path) -> None:
    Cache(tmp_path).set("thing", [1, 2, 3])
    assert Cache(tmp_path).get("thing") == [1, 2, 3]


def test_cache_namespaces_survive_windows_reserved_characters(tmp_path) -> None:
    """Namespaces contain ':' which Windows rejects in file names."""
    namespaces = [
        "session_token:track:4cOdK2wGLETKBW3PvgPWqT",
        "match:4cOdK2wGLETKBW3PvgPWqT",
        "canonical:The Weeknd|Blinding Lights|200040",
    ]
    cache = Cache(tmp_path)
    for namespace in namespaces:
        cache.set(namespace, namespace)

    assert list(tmp_path.glob("*.json")), "no cache files were written"

    fresh = Cache(tmp_path)
    for namespace in namespaces:
        assert fresh.get(namespace) == namespace
        assert fresh.get(namespace) is not None


def test_cache_name_is_legal_on_windows(tmp_path) -> None:
    cache = Cache(tmp_path)
    cache.set("weird:name/with\\chars", 1)
    for path in tmp_path.glob("*.json"):
        assert not any(char in path.name for char in '<>:"/\\|?*')
