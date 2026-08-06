from lexical import LexicalIndex, tokenize


class FakeGetCollection:
    def __init__(self, ids, docs, metas):
        self._payload = {"ids": ids, "documents": docs, "metadatas": metas}

    def get(self, include=None):
        return self._payload


def build_index():
    return LexicalIndex.build(FakeGetCollection(
        ids=["a_chunk_0", "b_chunk_0", "c_chunk_0"],
        docs=[
            "sourdough starter feeding schedule flour water",
            "rust borrow checker lifetime CHUNK_SIZE mutable",
            "marathon training taper mileage sunday",
        ],
        metas=[
            {"source": "a.md", "title": "Sourdough", "category": "note"},
            {"source": "b.md", "title": "Rust", "category": "chat"},
            {"source": "c.md", "title": "Marathon", "category": "note"},
        ],
    ))


def test_tokenize_keeps_snake_case_and_lowers():
    assert tokenize("Set CHUNK_SIZE=500, ok?") == ["set", "chunk_size", "500", "ok"]


def test_exact_token_ranks_right_chunk_first():
    index = build_index()
    out = index.search("chunk_size", scope="all", k=3)
    assert out[0]["source"] == "b.md"
    assert out[0]["id"] == "b_chunk_0"
    assert out[0]["score"] > 0


def test_scope_filter_notes_excludes_chats():
    index = build_index()
    sources = [c["source"] for c in index.search("sourdough rust marathon", scope="notes", k=5)]
    assert "b.md" not in sources
    assert set(sources) <= {"a.md", "c.md"}


def test_scope_filter_chats_only():
    index = build_index()
    sources = [c["source"] for c in index.search("rust borrow", scope="chats", k=5)]
    assert sources == ["b.md"]


def test_no_overlap_returns_empty():
    index = build_index()
    assert index.search("zzz qqq", scope="all", k=3) == []


def test_empty_corpus_and_empty_query():
    empty = LexicalIndex.build(FakeGetCollection([], [], []))
    assert len(empty) == 0
    assert empty.search("anything") == []
    index = build_index()
    assert index.search("   ") == []
