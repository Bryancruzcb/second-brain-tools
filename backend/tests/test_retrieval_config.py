"""Retrieval depth and top-k knobs resolve from env with safe defaults.

TOP_K / HYBRID_DEPTH / RERANK_DEPTH are the shipped defaults measured on
2026-09-04 (depth 30, k=6); the env overrides let a deployment flip to
k=8 (with OLLAMA_NUM_CTX=16384) or sweep depths without a code change.
"""
import importlib

import config
import retrieval

KNOBS = ("TOP_K", "HYBRID_DEPTH", "RERANK_DEPTH")


def _clear(monkeypatch):
    for name in KNOBS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_the_shipped_config(monkeypatch):
    _clear(monkeypatch)
    assert config.get_top_k() == 6
    assert config.get_hybrid_depth() == 30
    assert config.get_rerank_depth() == 30


def test_env_overrides_parse_as_ints(monkeypatch):
    monkeypatch.setenv("TOP_K", "8")
    monkeypatch.setenv("HYBRID_DEPTH", "40")
    monkeypatch.setenv("RERANK_DEPTH", "35")
    assert config.get_top_k() == 8
    assert config.get_hybrid_depth() == 40
    assert config.get_rerank_depth() == 35


def test_garbage_or_nonpositive_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("TOP_K", "lots")
    monkeypatch.setenv("HYBRID_DEPTH", "0")
    monkeypatch.setenv("RERANK_DEPTH", "-3")
    assert config.get_top_k() == 6
    assert config.get_hybrid_depth() == 30
    assert config.get_rerank_depth() == 30


def test_retrieval_module_constants_follow_env(monkeypatch):
    # The constants bind at import, the same moment uvicorn, the eval and
    # the sweep script read them, so the override is observed via a reload.
    monkeypatch.setenv("TOP_K", "8")
    monkeypatch.setenv("HYBRID_DEPTH", "40")
    monkeypatch.setenv("RERANK_DEPTH", "35")
    try:
        importlib.reload(retrieval)
        assert (retrieval.TOP_K, retrieval.HYBRID_DEPTH, retrieval.RERANK_DEPTH) == (8, 40, 35)
    finally:
        _clear(monkeypatch)
        importlib.reload(retrieval)
    assert retrieval.TOP_K == config.get_top_k()
    assert retrieval.HYBRID_DEPTH == config.get_hybrid_depth()
    assert retrieval.RERANK_DEPTH == config.get_rerank_depth()
