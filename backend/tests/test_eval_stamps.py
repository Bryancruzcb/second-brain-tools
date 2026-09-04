"""stamp_mismatch(): why an index cannot be scored under the current config.

Pure function over the collection metadata, so the refusal logic is tested
without Chroma or a model."""
from eval.run_eval import stamp_mismatch

MODEL = "BAAI/bge-small-en-v1.5"


def test_matching_stamps_are_fine():
    meta = {"embedding_model": MODEL, "chunk_scheme": "plain"}
    assert stamp_mismatch(meta, configured_model=MODEL, configured_scheme="plain") is None


def test_model_mismatch_names_both_models():
    msg = stamp_mismatch({"embedding_model": "all-MiniLM-L6-v2"}, configured_model=MODEL, configured_scheme="plain")
    assert "all-MiniLM-L6-v2" in msg and MODEL in msg and "--full" in msg


def test_scheme_mismatch_names_both_schemes():
    meta = {"embedding_model": MODEL, "chunk_scheme": "plain"}
    msg = stamp_mismatch(meta, configured_model=MODEL, configured_scheme="context-header")
    assert "plain" in msg and "context-header" in msg and "--full" in msg


def test_missing_scheme_stamp_counts_as_plain():
    meta = {"embedding_model": MODEL}
    assert stamp_mismatch(meta, configured_model=MODEL, configured_scheme="plain") is None
    msg = stamp_mismatch(meta, configured_model=MODEL, configured_scheme="context-header")
    assert msg and "plain" in msg and "context-header" in msg


def test_missing_model_stamp_is_not_a_mismatch():
    # Pre-stamp indexes are legal; main() warns about them separately.
    assert stamp_mismatch({}, configured_model=MODEL, configured_scheme="plain") is None
    assert stamp_mismatch(None, configured_model=MODEL, configured_scheme="plain") is None
