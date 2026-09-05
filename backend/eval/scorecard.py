"""The committed eval scorecard: what CI can hold the published number to.

The dataset and the vault never leave this machine, so CI cannot re-score
retrieval. What it can do is refuse a stale claim. The scorecard records
the metrics, the retrieval config they were measured under, a census of
the index and a hash of the dataset, and never a question or a note path.
A test fails when the shipped config no longer matches it or when the
README block stops matching it, so changing a retrieval setting without
re-running the eval fails CI. The nightly archive job covers the other
half by re-scoring locally and warning on drift (run_eval.py --check).

Pure functions only: no Chroma, no models, and no I/O beyond the history
file appender.
"""
import json

import config as _cfg

START_MARKER = "<!-- eval-scorecard:start -->"
END_MARKER = "<!-- eval-scorecard:end -->"
PRIVATE_KEYS = ("question", "expected_sources", "retrieved")
DRIFT_POINTS = 5.0  # two cases out of forty, above the one-case rebuild jitter


def effective_config():
    """The retrieval settings in force for this process."""
    return {
        "embedding_model": _cfg.get_embedding_model(),
        "query_prefix": bool(_cfg.get_query_prefix()),
        "reranker_model": _cfg.get_reranker_model(),
        "hybrid_depth": _cfg.get_hybrid_depth(),
        "rerank_depth": _cfg.get_rerank_depth(),
        "top_k": _cfg.get_top_k(),
        "max_chunks_per_note": _cfg.get_max_chunks_per_note(),
        # Arrives with the contextual-chunk-header work; "plain" until then.
        "chunk_scheme": getattr(_cfg, "get_chunk_scheme", lambda: "plain")(),
    }


def build_scorecard(*, config, index, dataset, summary, recorded_at):
    """Assemble the scorecard from a run summary and the census dicts."""
    return {
        "recorded_at": recorded_at,
        "config": dict(config),
        "index": dict(index),
        "dataset": dict(dataset),
        "metrics": {
            "k": summary["k"],
            "hit_rate": summary["hit_rate"],
            "mrr": summary["mrr"],
            "by_k": {
                str(k): {"hit_rate": row["hit_rate"], "mrr": row["mrr"]}
                for k, row in summary["by_k"].items()
            },
        },
    }


def private_keys_found(obj):
    """Names from PRIVATE_KEYS found anywhere in a nested structure, in order."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in PRIVATE_KEYS and key not in found:
                    found.append(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


def render_readme_block(card):
    """Markdown for the README block: one summary line, one row per k."""
    cfg, idx, ds, metrics = card["config"], card["index"], card["dataset"], card["metrics"]
    prefix = "with its query instruction" if cfg["query_prefix"] else "without a query instruction"
    if _cfg.reranker_disabled(cfg["reranker_model"]):
        rerank = "no reranker"
    else:
        rerank = f"the fused top {cfg['rerank_depth']} reranked by `{cfg['reranker_model']}`"
    scheme = "" if cfg["chunk_scheme"] == "plain" else f", chunk scheme `{cfg['chunk_scheme']}`"
    cap = cfg.get("max_chunks_per_note", 0)
    per_note = f", at most {cap} per note" if cap else ""
    lines = [
        f"Recorded {card['recorded_at']} over {ds['cases']} cases against an index of "
        f"{idx['chunks']:,} chunks from {idx['sources']:,} files ({idx['notes']} notes, "
        f"{idx['chats']} chat transcripts): `{cfg['embedding_model']}` embeddings {prefix}, "
        f"each leg fetched to depth {cfg['hybrid_depth']}, {rerank}, "
        f"{cfg['top_k']} chunks served{per_note}{scheme}.",
        "",
        "| Chunks shown | Hit-rate | MRR |",
        "|---|---|---|",
    ]
    for k in sorted(metrics["by_k"], key=int):
        row = metrics["by_k"][k]
        label = f"{k} (shipped)" if int(k) == metrics["k"] else k
        lines.append(f"| {label} | {row['hit_rate']:.1%} | {row['mrr']:.3f} |")
    return "\n".join(lines)


def _marker_span(text):
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < 0 or end < start:
        raise ValueError(f"README is missing the {START_MARKER} / {END_MARKER} markers")
    return start + len(START_MARKER), end


def replace_block(text, rendered):
    """Swap the content between the markers, keeping the file's own newlines."""
    start, end = _marker_span(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    body = newline.join(rendered.splitlines())
    return text[:start] + newline + body + newline + text[end:]


def extract_block(text):
    """The content between the markers, without the surrounding newlines."""
    start, end = _marker_span(text)
    return text[start:end].strip("\r\n")


def drift_verdict(current_hit_rate, recorded_hit_rate, cases):
    """(drifted, message). Warns when hit-rate fell DRIFT_POINTS or more."""
    drop_points = round((recorded_hit_rate - current_hit_rate) * 100, 1)
    current, recorded = f"{current_hit_rate:.1%}", f"{recorded_hit_rate:.1%}"
    if drop_points >= DRIFT_POINTS:
        lost = round(drop_points / 100 * cases)
        return True, f"EVAL DRIFT WARNING: hit-rate {current} vs recorded {recorded} ({lost} cases)"
    return False, f"EVAL OK: hit-rate {current} vs recorded {recorded}"


def append_history(path, entry):
    """Append one JSON line; the file is local and gitignored."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
