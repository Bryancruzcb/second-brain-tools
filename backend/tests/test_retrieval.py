import retrieval


class FakeModel:
    def encode(self, texts):
        import numpy as np
        return np.zeros((len(texts), 4), dtype=np.float32)


class FakeCollection:
    """Records query kwargs and returns a canned Chroma-shaped result."""
    def __init__(self, result):
        self.result = result
        self.last_kwargs = None

    def query(self, **kwargs):
        self.last_kwargs = kwargs
        return self.result


CANNED = {
    "documents": [["chunk one text", "chunk two text"]],
    "metadatas": [[{"source": "a.md", "title": "A"}, {"source": "b.md", "title": "B"}]],
    "distances": [[0.1, 0.4]],
}


def test_retrieve_parses_chroma_results_into_candidates():
    coll = FakeCollection(CANNED)
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out == [
        {"source": "a.md", "title": "A", "chunk": "chunk one text", "distance": 0.1},
        {"source": "b.md", "title": "B", "chunk": "chunk two text", "distance": 0.4},
    ]


def test_retrieve_passes_k_and_scope_filter():
    coll = FakeCollection(CANNED)
    retrieval.retrieve("q", model=FakeModel(), collection=coll, scope="chats", k=7)
    assert coll.last_kwargs["n_results"] == 7
    assert coll.last_kwargs["where"] == {"category": "chat"}


def test_retrieve_handles_empty_results():
    coll = FakeCollection({"documents": [[]], "metadatas": [[]], "distances": [[]]})
    assert retrieval.retrieve("q", model=FakeModel(), collection=coll) == []


def test_scope_filters():
    assert retrieval.scope_filter("chats") == {"category": "chat"}
    assert retrieval.scope_filter("notes") == {"category": {"$ne": "chat"}}
    assert retrieval.scope_filter("all") is None


def test_missing_metadata_gets_defaults():
    coll = FakeCollection({
        "documents": [["text"]],
        "metadatas": [[None]],
        "distances": [[0.2]],
    })
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out[0]["source"] == ""
    assert out[0]["title"] == "Untitled Note"
