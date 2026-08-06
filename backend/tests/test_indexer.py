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
