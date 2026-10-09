import ask_cache
import config


def test_ttl_default_and_overrides(monkeypatch):
    monkeypatch.delenv("ASK_CACHE_TTL_SECONDS", raising=False)
    assert config.get_ask_cache_ttl_seconds() == 900
    monkeypatch.setenv("ASK_CACHE_TTL_SECONDS", "0")
    assert config.get_ask_cache_ttl_seconds() == 0
    for bad in ("-5", "soon"):
        monkeypatch.setenv("ASK_CACHE_TTL_SECONDS", bad)
        assert config.get_ask_cache_ttl_seconds() == 900


def test_lru_evicts_the_least_recently_read(monkeypatch):
    monkeypatch.delenv("ASK_CACHE_TTL_SECONDS", raising=False)
    cache = ask_cache.TTLCache(maxsize=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # a is now the most recent
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1 and cache.get("c") == 3


def test_entries_expire_after_the_ttl(monkeypatch):
    monkeypatch.setenv("ASK_CACHE_TTL_SECONDS", "10")
    now = [1000.0]
    monkeypatch.setattr(ask_cache.time, "monotonic", lambda: now[0])
    cache = ask_cache.TTLCache(maxsize=4)
    cache.put("k", "v")
    now[0] += 10
    assert cache.get("k") == "v"
    now[0] += 0.5
    assert cache.get("k") is None
    assert len(cache) == 0
