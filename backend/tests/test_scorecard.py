"""The committed eval scorecard and the two halves of the drift watch.

CI cannot read the private vault, so it checks the scorecard against the
shipped config and the README block instead; the nightly archive job
re-scores the private set and warns on drift. No model loads here.
"""
import json
import os
import sys

import pytest

from eval import run_eval
from eval.scorecard import (
    END_MARKER, START_MARKER, append_history, build_scorecard, drift_verdict,
    effective_config, extract_block, private_keys_found, render_readme_block,
    replace_block,
)

KNOB_ENV = ("TOP_K", "HYBRID_DEPTH", "RERANK_DEPTH", "EMBEDDING_MODEL",
            "EMBEDDING_QUERY_PREFIX", "RERANKER_MODEL", "CHUNK_SCHEME")
RECORD_HINT = ("run `python -m eval.run_eval --record` from backend/ "
               "and commit backend/eval/scorecard.json")

SUMMARY = {
    "hit_rate": 0.825, "mrr": 0.73, "cases": 40, "ungradable": 0, "k": 6,
    "by_k": {"4": {"hit_rate": 0.8, "mrr": 0.717}, "6": {"hit_rate": 0.825, "mrr": 0.73}},
}
INDEX = {"chunks": 4321, "sources": 304, "notes": 63, "chats": 241,
         "embedding_model_stamp": "BAAI/bge-small-en-v1.5"}
DATASET = {"cases": 40, "sha256": "ab" * 32}


def _clear_knobs(monkeypatch):
    for name in KNOB_ENV:
        monkeypatch.delenv(name, raising=False)


def _scorecard(monkeypatch):
    _clear_knobs(monkeypatch)
    return build_scorecard(config=effective_config(), index=INDEX, dataset=DATASET,
                           summary=SUMMARY, recorded_at="2026-09-04")


def _committed_scorecard():
    if not os.path.exists(run_eval.SCORECARD_PATH):
        pytest.skip(f"no scorecard recorded yet: {RECORD_HINT}")
    with open(run_eval.SCORECARD_PATH, encoding="utf-8") as f:
        return json.load(f)


# ── building ────────────────────────────────────────────────────────────────

def test_scorecard_has_exactly_the_published_schema(monkeypatch):
    card = _scorecard(monkeypatch)
    assert set(card) == {"recorded_at", "config", "index", "dataset", "metrics"}
    assert card["recorded_at"] == "2026-09-04"
    assert set(card["config"]) == {"embedding_model", "query_prefix", "reranker_model",
                                   "hybrid_depth", "rerank_depth", "top_k", "chunk_scheme"}
    assert card["index"] == INDEX
    assert card["dataset"] == DATASET
    assert card["metrics"] == {"k": 6, "hit_rate": 0.825, "mrr": 0.73, "by_k": SUMMARY["by_k"]}


def test_scorecard_carries_no_private_fields(monkeypatch):
    assert private_keys_found(_scorecard(monkeypatch)) == []
    leaky = {"metrics": {"cases": [{"question": "q", "retrieved": ["x.md"]}]}}
    assert private_keys_found(leaky) == ["question", "retrieved"]


def test_effective_config_reads_env_and_defaults(monkeypatch):
    _clear_knobs(monkeypatch)
    cfg = effective_config()
    assert (cfg["top_k"], cfg["hybrid_depth"], cfg["rerank_depth"]) == (6, 30, 30)
    assert cfg["query_prefix"] is True
    assert cfg["chunk_scheme"] == "plain"
    monkeypatch.setenv("TOP_K", "8")
    monkeypatch.setenv("RERANKER_MODEL", "some/other-model")
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "")
    cfg = effective_config()
    assert cfg["top_k"] == 8
    assert cfg["reranker_model"] == "some/other-model"
    assert cfg["query_prefix"] is False


# ── README block ────────────────────────────────────────────────────────────

def test_render_lists_the_date_config_and_one_row_per_k(monkeypatch):
    text = render_readme_block(_scorecard(monkeypatch))
    assert "2026-09-04" in text
    assert "cross-encoder/ms-marco-MiniLM-L-6-v2" in text
    assert "4,321" in text and "40 cases" in text
    rows = [line for line in text.splitlines() if line.startswith("| ")]
    assert any("80.0%" in r and "0.717" in r for r in rows)
    assert any("82.5%" in r and "0.730" in r and "shipped" in r for r in rows)


def test_replace_block_swaps_only_the_marked_region():
    doc = f"before\n{START_MARKER}\nold\n{END_MARKER}\nafter\n"
    out = replace_block(doc, "new line one\nnew line two")
    assert out == f"before\n{START_MARKER}\nnew line one\nnew line two\n{END_MARKER}\nafter\n"
    assert extract_block(out) == "new line one\nnew line two"


def test_replace_block_keeps_the_files_crlf_endings():
    doc = f"before\r\n{START_MARKER}\r\nold\r\n{END_MARKER}\r\nafter\r\n"
    out = replace_block(doc, "a\nb")
    assert out == f"before\r\n{START_MARKER}\r\na\r\nb\r\n{END_MARKER}\r\nafter\r\n"


def test_replace_block_requires_both_markers():
    with pytest.raises(ValueError):
        replace_block("no markers here\n", "x")


# ── drift rule and history ──────────────────────────────────────────────────

def test_drift_rule_four_point_nine_is_fine_and_five_warns():
    drifted, message = drift_verdict(0.776, 0.825, cases=40)
    assert drifted is False
    assert message.startswith("EVAL OK")
    drifted, message = drift_verdict(0.775, 0.825, cases=40)
    assert drifted is True
    assert message == "EVAL DRIFT WARNING: hit-rate 77.5% vs recorded 82.5% (2 cases)"


def test_drift_rule_treats_improvement_as_ok():
    drifted, message = drift_verdict(0.85, 0.825, cases=40)
    assert drifted is False
    assert message == "EVAL OK: hit-rate 85.0% vs recorded 82.5%"


def test_append_history_writes_one_json_line_per_call(tmp_path):
    path = tmp_path / "history.jsonl"
    append_history(str(path), {"date": "2026-09-04", "hit_rate": 0.825})
    append_history(str(path), {"date": "2026-09-05", "hit_rate": 0.8})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["date"] for l in lines] == ["2026-09-04", "2026-09-05"]


# ── --check preconditions ───────────────────────────────────────────────────

@pytest.mark.parametrize("missing", ["dataset", "scorecard"])
def test_check_skips_quietly_when_dataset_or_scorecard_is_missing(tmp_path, monkeypatch, capsys, missing):
    dataset = tmp_path / "dataset.jsonl"
    scorecard = tmp_path / "scorecard.json"
    if missing != "dataset":
        dataset.write_text('{"question": "q", "expected_sources": ["a.md"]}\n', encoding="utf-8")
    if missing != "scorecard":
        scorecard.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(run_eval, "DEFAULT_DATASET", str(dataset))
    monkeypatch.setattr(run_eval, "SCORECARD_PATH", str(scorecard))
    monkeypatch.setattr(sys, "argv", ["run_eval", "--check"])
    run_eval.main()  # returns instead of exiting: other machines lack the private set
    out = capsys.readouterr().out
    assert "skip" in out.lower() and missing in out.lower()


def test_readme_carries_the_markers_and_round_trips_with_its_own_newlines(monkeypatch):
    with open(run_eval.README_PATH, encoding="utf-8", newline="") as f:
        readme = f.read()
    rendered = render_readme_block(_scorecard(monkeypatch))
    updated = replace_block(readme, rendered)
    assert extract_block(updated).replace("\r\n", "\n") == rendered
    assert ("\r\n" in readme) == ("\r\n" in updated)  # no mixed endings introduced


# ── the committed scorecard, when present ───────────────────────────────────

def test_committed_scorecard_matches_the_shipped_config(monkeypatch):
    card = _committed_scorecard()
    _clear_knobs(monkeypatch)
    assert card["config"] == effective_config(), (
        f"scorecard.json was recorded under a different retrieval config; {RECORD_HINT}")


def test_committed_scorecard_has_no_private_fields():
    assert private_keys_found(_committed_scorecard()) == []


def test_readme_block_matches_the_committed_scorecard():
    card = _committed_scorecard()
    with open(run_eval.README_PATH, encoding="utf-8") as f:
        readme = f.read()
    assert extract_block(readme).strip() == render_readme_block(card).strip(), (
        f"README scorecard block is stale; {RECORD_HINT}")
