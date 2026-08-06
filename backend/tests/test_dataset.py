import pytest

from eval.dataset import DatasetError, load_dataset


def write(tmp_path, text):
    p = tmp_path / "dataset.jsonl"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_loads_valid_cases_and_defaults_scope(tmp_path):
    path = write(tmp_path, (
        '{"question": "what is X?", "expected_sources": ["03 Projects/X.md"]}\n'
        '\n'  # blank lines are skipped
        '{"question": "chat Q", "expected_sources": ["05 AI Chats/a.md"], "scope": "chats"}\n'
    ))
    cases = load_dataset(path)
    assert len(cases) == 2
    assert cases[0] == {"question": "what is X?",
                        "expected_sources": ["03 Projects/X.md"], "scope": "notes"}
    assert cases[1]["scope"] == "chats"


def test_invalid_json_reports_line_number(tmp_path):
    path = write(tmp_path, '{"question": "ok", "expected_sources": ["a.md"]}\n{broken\n')
    with pytest.raises(DatasetError, match=":2:"):
        load_dataset(path)


def test_non_object_json_line_rejected(tmp_path):
    path = write(tmp_path, '[1]\n')
    with pytest.raises(DatasetError, match=":1:"):
        load_dataset(path)


def test_empty_question_rejected(tmp_path):
    path = write(tmp_path, '{"question": "  ", "expected_sources": ["a.md"]}\n')
    with pytest.raises(DatasetError, match="question"):
        load_dataset(path)


def test_missing_expected_sources_rejected(tmp_path):
    path = write(tmp_path, '{"question": "q", "expected_sources": []}\n')
    with pytest.raises(DatasetError, match="expected_sources"):
        load_dataset(path)


def test_bad_scope_rejected(tmp_path):
    path = write(tmp_path, '{"question": "q", "expected_sources": ["a.md"], "scope": "everything"}\n')
    with pytest.raises(DatasetError, match="scope"):
        load_dataset(path)


def test_empty_dataset_rejected(tmp_path):
    path = write(tmp_path, "\n")
    with pytest.raises(DatasetError, match="empty"):
        load_dataset(path)
