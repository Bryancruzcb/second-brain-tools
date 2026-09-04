import os
import uuid

import chromadb
import pytest

import config
import indexer
from tests.fakes import BagOfWordsEmbedder

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class ExplodingModel:
    def encode(self, texts):
        raise RuntimeError("model exploded")


@pytest.fixture()
def vault_env(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", os.path.join(FIXTURES, "vault"))
    monkeypatch.setenv("EMBEDDING_MODEL", "model-a")
    # chromadb caches one in-memory System per settings hash, so repeated
    # EphemeralClient() calls share state — a fixed collection name would
    # hand the next test the previous test's (already stamped) collection.
    return chromadb.EphemeralClient().get_or_create_collection(f"hardening_{uuid.uuid4().hex}")


def test_full_rebuild_stamps_embedding_model(vault_env):
    collection = vault_env
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    assert summary["batches_failed"] == 0
    assert summary["chunks_written"] >= 5
    assert collection.metadata["embedding_model"] == "model-a"


def test_full_rebuild_stamps_collection_with_legacy_hnsw_metadata(vault_env):
    # Chroma rejects any modify() payload containing "hnsw:space" — even when
    # the value is unchanged — so a naive read-modify-write silently fails to
    # stamp collections whose metadata carries that legacy key.
    collection = chromadb.EphemeralClient().get_or_create_collection(
        f"hardening_legacy_{uuid.uuid4().hex}",
        metadata={"hnsw:space": "cosine", "note": "keep me"},
    )
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    assert summary["batches_failed"] == 0
    assert collection.metadata["embedding_model"] == "model-a"
    assert collection.metadata["note"] == "keep me"  # unrelated keys survive


def test_incremental_aborts_on_stamp_mismatch(vault_env, monkeypatch):
    collection = vault_env
    indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    before = collection.count()

    monkeypatch.setenv("EMBEDDING_MODEL", "model-b")
    # Touch a file's mtime so a non-aborting incremental would re-embed it.
    target = os.path.join(FIXTURES, "vault", "Sourdough Starter.md")
    os.utime(target, None)

    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=lambda *_: None)
    assert "aborted" in summary
    assert "model-a" in summary["aborted"] and "model-b" in summary["aborted"]
    assert summary["chunks_written"] == 0
    assert collection.count() == before  # nothing was written or deleted


def test_incremental_with_matching_stamp_proceeds(vault_env):
    collection = vault_env
    indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=lambda *_: None)
    assert "aborted" not in summary
    assert summary["files_scanned"] >= 5


def test_unstamped_incremental_warns_but_proceeds(vault_env):
    collection = vault_env
    messages = []
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=messages.append)
    assert "aborted" not in summary
    assert any("stamp" in str(m) for m in messages)
    assert collection.metadata is None or "embedding_model" not in (collection.metadata or {})


def test_failed_batches_are_counted(vault_env):
    collection = vault_env
    summary = indexer.index_vault(collection, ExplodingModel(), incremental=False, log=lambda *_: None)
    assert summary["batches_failed"] >= 1
    assert summary["chunks_written"] == 0


class WipeFailingCollection:
    """Delegates to a real collection but fails the full-rebuild wipe."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def metadata(self):
        return self._inner.metadata

    def delete(self, *args, **kwargs):
        raise RuntimeError("wipe failed")


def test_failed_wipe_does_not_stamp(vault_env):
    collection = vault_env
    # Populate so the wipe has something to delete (and therefore fails).
    indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)

    # Second full rebuild under a NEW model, with a failing wipe: stamping
    # would assert the new model over chunks the wipe never removed.
    os.environ["EMBEDDING_MODEL"] = "model-b"
    try:
        wrapped = WipeFailingCollection(collection)
        summary = indexer.index_vault(wrapped, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
        assert collection.metadata["embedding_model"] == "model-a"  # old stamp kept
        # ...and the failure is visible to callers, not just withheld silently:
        # rebuild_rag_index.py exits nonzero on this flag.
        assert summary["wipe_failed"] is True
    finally:
        os.environ["EMBEDDING_MODEL"] = "model-a"


# ── chunk scheme: context headers ───────────────────────────────────────────

def test_context_header_scheme_prefixes_documents_and_stamps(vault_env, monkeypatch):
    monkeypatch.setenv("CHUNK_SCHEME", "context-header")
    collection = vault_env
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    assert summary["batches_failed"] == 0
    assert collection.metadata["chunk_scheme"] == "context-header"
    assert collection.metadata["embedding_model"] == "model-a"  # both stamps, one modify
    got = collection.get(include=["documents", "metadatas"])
    assert got["documents"]
    for doc, meta in zip(got["documents"], got["metadatas"]):
        assert meta["context"]
        assert doc.startswith(meta["context"] + "\n\n")
    by_source = {m["source"]: m["context"] for m in got["metadatas"]}
    # Root-level note whose only heading repeats the title: the header is
    # the title alone, not "Sourdough Starter > Sourdough Starter".
    assert by_source["Sourdough Starter.md"] == "Sourdough Starter"


def test_plain_scheme_stamps_plain_and_writes_no_context(vault_env, monkeypatch):
    monkeypatch.delenv("CHUNK_SCHEME", raising=False)
    collection = vault_env
    indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    assert collection.metadata["chunk_scheme"] == "plain"
    got = collection.get(include=["documents", "metadatas"])
    assert all("context" not in m for m in got["metadatas"])
    assert any(d.startswith("# Sourdough Starter") for d in got["documents"])


def test_incremental_aborts_on_chunk_scheme_mismatch(vault_env, monkeypatch):
    monkeypatch.delenv("CHUNK_SCHEME", raising=False)
    collection = vault_env
    indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    before = collection.count()

    monkeypatch.setenv("CHUNK_SCHEME", "context-header")
    os.utime(os.path.join(FIXTURES, "vault", "Sourdough Starter.md"), None)

    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=lambda *_: None)
    assert "aborted" in summary
    assert "plain" in summary["aborted"] and "context-header" in summary["aborted"]
    assert "rebuild_rag_index.py --full" in summary["aborted"]
    assert summary["chunks_written"] == 0
    assert collection.count() == before


def test_unstamped_scheme_with_plain_config_is_silent(vault_env, monkeypatch):
    monkeypatch.delenv("CHUNK_SCHEME", raising=False)
    collection = vault_env
    messages = []
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=messages.append)
    assert "aborted" not in summary
    assert not any("scheme" in str(m).lower() for m in messages)


def test_unstamped_scheme_with_header_config_warns_but_proceeds(vault_env, monkeypatch):
    monkeypatch.setenv("CHUNK_SCHEME", "context-header")
    collection = vault_env
    messages = []
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=messages.append)
    assert "aborted" not in summary
    assert summary["chunks_written"] >= 5
    assert any("scheme" in str(m).lower() for m in messages)
