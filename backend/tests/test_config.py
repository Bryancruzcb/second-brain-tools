import config


def test_embedding_model_default_and_override(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    assert config.get_embedding_model() == "BAAI/bge-small-en-v1.5"
    monkeypatch.setenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    assert config.get_embedding_model() == "all-MiniLM-L6-v2"


def test_query_prefix_defaults_to_bge_instruction(monkeypatch):
    monkeypatch.delenv("EMBEDDING_QUERY_PREFIX", raising=False)
    assert config.get_query_prefix() == (
        "Represent this sentence for searching relevant passages: "
    )
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "query: ")
    assert config.get_query_prefix() == "query: "
    # An empty override must stick (models without a query instruction).
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "")
    assert config.get_query_prefix() == ""


def test_reranker_disabled_values():
    for value in ("", "off", "OFF", " none ", "Disabled"):
        assert config.reranker_disabled(value)
    assert not config.reranker_disabled("cross-encoder/ms-marco-MiniLM-L-6-v2")


def test_reranker_onnx_file_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("RERANKER_ONNX_FILE", raising=False)
    assert config.get_reranker_onnx_file() == ""
    monkeypatch.setenv("RERANKER_ONNX_FILE", " onnx/model_quantized.onnx ")
    assert config.get_reranker_onnx_file() == "onnx/model_quantized.onnx"
