import config


def test_embedding_model_default_and_override(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    assert config.get_embedding_model() == "BAAI/bge-small-en-v1.5"
    monkeypatch.setenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    assert config.get_embedding_model() == "all-MiniLM-L6-v2"


def test_query_prefix_default_empty(monkeypatch):
    monkeypatch.delenv("EMBEDDING_QUERY_PREFIX", raising=False)
    assert config.get_query_prefix() == ""
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "query: ")
    assert config.get_query_prefix() == "query: "


def test_reranker_disabled_values():
    for value in ("", "off", "OFF", " none ", "Disabled"):
        assert config.reranker_disabled(value)
    assert not config.reranker_disabled("cross-encoder/ms-marco-MiniLM-L-6-v2")
