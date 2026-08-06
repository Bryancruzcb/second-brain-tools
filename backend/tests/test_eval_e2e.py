import os

import chromadb
import pytest

import indexer
from eval.dataset import load_dataset
from eval.run_eval import run
from lexical import LexicalIndex
from tests.fakes import BagOfWordsEmbedder

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture()
def indexed_collection(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", os.path.join(FIXTURES, "vault"))
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("eval_e2e")
    embedder = BagOfWordsEmbedder()
    summary = indexer.index_vault(collection, embedder, incremental=False, log=lambda *_: None)
    assert summary["chunks_written"] >= 5
    lex = LexicalIndex.build(collection)
    return collection, embedder, lex


def test_eval_end_to_end_on_fixture_vault(indexed_collection):
    collection, embedder, lex = indexed_collection
    cases = load_dataset(os.path.join(FIXTURES, "dataset.jsonl"))

    rows, summary = run(cases, model=embedder, collection=collection, lexical=lex, k=4)

    by_q = {r["question"]: r for r in rows}
    assert by_q["how often do I feed the sourdough starter?"]["status"] == "hit"
    assert by_q["why does the borrow checker reject mutable references?"]["status"] == "hit"
    # Expected note absent from the index -> reported ungradable, not a miss.
    assert by_q["note that does not exist anywhere"]["status"] == "ungradable"
    # Indexed note that neither leg surfaces in the top 4 -> a real miss.
    assert by_q["sourdough starter borrow checker marathon taper coffee grinder"]["status"] == "miss"
    assert by_q["sourdough starter borrow checker marathon taper coffee grinder"]["rank"] is None

    assert summary["cases"] == 3
    assert summary["ungradable"] == 1
    assert summary["hit_rate"] == 2 / 3
    assert summary["mrr"] == (1.0 + 1.0 + 0.0) / 3
    assert summary["k"] == 4


def test_chunks_carry_section_heading_metadata(indexed_collection):
    collection, _, _ = indexed_collection
    got = collection.get(include=["metadatas"])
    headings = {m["source"]: m.get("heading") for m in got["metadatas"]}
    assert headings["Sourdough Starter.md"] == "Sourdough Starter"
    assert headings["Rust Borrow Checker.md"] == "Rust Borrow Checker"
