"""The public score CI runs.

This is not the private 40-question set.
"""
import os

import chromadb

import indexer
from eval.dataset import load_dataset
from eval.run_eval import run
from lexical import LexicalIndex
from tests.fakes import BagOfWordsEmbedder, OverlapCrossEncoder

PUBLIC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "eval",
    "public",
)


def test_public_fixture_hits(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", os.path.join(PUBLIC, "vault"))
    # Pin the query prefix off: the bag-of-words embedder is content-sensitive,
    # so the ranking assertions below must not drift with the shipped default
    # (or a stray .env entry pulled in by load_dotenv at main import).
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "")
    # CI has no Ollama. A local rewrite changes rank, so the public score is
    # the raw questions.
    monkeypatch.setenv("QUERY_REWRITE", "0")
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("public_fixture")
    embedder = BagOfWordsEmbedder()
    indexer.index_vault(collection, embedder, incremental=False, log=lambda *_: None)
    lex = LexicalIndex.build(collection)
    cases = load_dataset(os.path.join(PUBLIC, "questions.jsonl"))

    rows, summary = run(cases, model=embedder, collection=collection, lexical=lex,
                        cross_encoder=OverlapCrossEncoder(), k=4)

    by_q = {r["question"]: r for r in rows}
    expected = {
        "levain hydration overnight": "Levain.md",
        "balance greens browns aeration": "Compost Bin.md",
        "cadence meter repeats": "Track Intervals.md",
    }
    for question, source in expected.items():
        row = by_q[question]
        assert row["status"] == "hit", row
        assert row["retrieved"][0] == source, row

    assert summary["cases"] == 3
    assert summary["ungradable"] == 0
    assert summary["hit_rate"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["k"] == 4
