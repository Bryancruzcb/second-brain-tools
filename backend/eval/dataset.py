"""Load and validate the eval dataset.

Format: JSONL, one case per line:
    {"question": "...", "expected_sources": ["vault/relative/path.md"], "scope": "notes"}
expected_sources are vault-relative paths matching the chunk metadata
"source" field; scope is optional ("notes" default, or "chats"/"all").
"""
import json

VALID_SCOPES = ("notes", "chats", "all")


class DatasetError(ValueError):
    pass


def load_dataset(path):
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise DatasetError(f"{path}:{lineno}: invalid JSON: {e}") from e

            if not isinstance(obj, dict):
                raise DatasetError(
                    f"{path}:{lineno}: line must be a JSON object, got {type(obj).__name__}")

            question = obj.get("question")
            if not isinstance(question, str) or not question.strip():
                raise DatasetError(f"{path}:{lineno}: 'question' must be a non-empty string")

            expected = obj.get("expected_sources")
            if (not isinstance(expected, list) or not expected
                    or not all(isinstance(s, str) and s.strip() for s in expected)):
                raise DatasetError(
                    f"{path}:{lineno}: 'expected_sources' must be a non-empty list of strings")

            scope = obj.get("scope", "notes")
            if scope not in VALID_SCOPES:
                raise DatasetError(
                    f"{path}:{lineno}: 'scope' must be one of {VALID_SCOPES}, got {scope!r}")

            cases.append({
                "question": question.strip(),
                "expected_sources": [s.strip() for s in expected],
                "scope": scope,
            })
    if not cases:
        raise DatasetError(f"{path}: dataset is empty")
    return cases
