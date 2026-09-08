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
    assert not config.reranker_disabled("Xenova/ms-marco-MiniLM-L-6-v2")


def test_reranker_model_default_is_xenova_onnx_pair(monkeypatch):
    monkeypatch.delenv("RERANKER_MODEL", raising=False)
    assert config.get_reranker_model() == "Xenova/ms-marco-MiniLM-L-6-v2"


def test_ollama_num_ctx_default_matches_top_k_eight(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    assert config.get_ollama_num_ctx() == 16384
    monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
    assert config.get_ollama_num_ctx() == 8192


def test_reranker_onnx_file_defaults_to_quantized_export(monkeypatch):
    monkeypatch.delenv("RERANKER_ONNX_FILE", raising=False)
    assert config.get_reranker_onnx_file() == "onnx/model_quantized.onnx"
    monkeypatch.setenv("RERANKER_ONNX_FILE", " onnx/model.onnx ")
    assert config.get_reranker_onnx_file() == "onnx/model.onnx"
    # Empty override opts back into sentence-transformers.
    monkeypatch.setenv("RERANKER_ONNX_FILE", "")
    assert config.get_reranker_onnx_file() == ""


def test_chunk_scheme_defaults_to_heading_aware(monkeypatch):
    monkeypatch.delenv("CHUNK_SCHEME", raising=False)
    assert config.get_chunk_scheme() == "heading-aware"
    monkeypatch.setenv("CHUNK_SCHEME", "plain")
    assert config.get_chunk_scheme() == "plain"
    monkeypatch.setenv("CHUNK_SCHEME", "  ")
    assert config.get_chunk_scheme() == "heading-aware"


def test_query_rewrite_defaults_on(monkeypatch):
    monkeypatch.delenv("QUERY_REWRITE", raising=False)
    assert config.query_rewrite_enabled() is True
    monkeypatch.setenv("QUERY_REWRITE", "0")
    assert config.query_rewrite_enabled() is False
    monkeypatch.setenv("QUERY_REWRITE", "1")
    assert config.query_rewrite_enabled() is True


def test_notes_chat_guard_defaults_on(monkeypatch):
    monkeypatch.delenv("NOTES_CHAT_GUARD", raising=False)
    assert config.notes_chat_guard_enabled() is True
    monkeypatch.setenv("NOTES_CHAT_GUARD", "off")
    assert config.notes_chat_guard_enabled() is False


def test_sibling_disambig_defaults_on(monkeypatch):
    monkeypatch.delenv("SIBLING_DISAMBIG", raising=False)
    assert config.sibling_disambig_enabled() is True
    monkeypatch.setenv("SIBLING_DISAMBIG", "false")
    assert config.sibling_disambig_enabled() is False
