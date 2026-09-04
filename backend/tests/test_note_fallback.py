"""get_indexed_note_text(): the read-only fallback for cloud placeholders
must hand back clean note text even when chunks carry context headers."""
import main


class FakeStore:
    def __init__(self, documents, metadatas):
        self._documents = documents
        self._metadatas = metadatas
        self.last_kwargs = None

    def get(self, **kwargs):
        self.last_kwargs = kwargs
        return {"documents": self._documents, "metadatas": self._metadatas}


def test_fallback_strips_context_headers(monkeypatch):
    store = FakeStore(
        ["Notes > Alpha > Intro\n\n# Alpha\nbody one", "Notes > Alpha > Details\n\nbody two"],
        [{"context": "Notes > Alpha > Intro"}, {"context": "Notes > Alpha > Details"}],
    )
    monkeypatch.setattr(main, "chroma_collection", store)
    assert main.get_indexed_note_text("Notes/Alpha.md") == "# Alpha\nbody one\n\nbody two"
    assert "metadatas" in store.last_kwargs["include"]


def test_fallback_leaves_plain_documents_alone(monkeypatch):
    store = FakeStore(["# Alpha\nbody one", "body two"], [{}, None])
    monkeypatch.setattr(main, "chroma_collection", store)
    assert main.get_indexed_note_text("Alpha.md") == "# Alpha\nbody one\n\nbody two"


def test_fallback_only_strips_a_header_the_document_carries(monkeypatch):
    store = FakeStore(["# Alpha\nbody"], [{"context": "Somewhere > Else"}])
    monkeypatch.setattr(main, "chroma_collection", store)
    assert main.get_indexed_note_text("Alpha.md") == "# Alpha\nbody"


def test_fallback_survives_missing_metadatas(monkeypatch):
    store = FakeStore(["body"], [])
    monkeypatch.setattr(main, "chroma_collection", store)
    assert main.get_indexed_note_text("Alpha.md") == "body"
