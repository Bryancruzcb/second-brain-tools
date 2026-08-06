from indexer import CHUNK_SIZE, chunk_text, split_sections


# ── split_sections ──────────────────────────────────────────────────────────

def test_splits_at_atx_headings_with_preamble():
    doc = "intro line\n\n# Alpha\nalpha body\n\n## Beta\nbeta body\n"
    sections = split_sections(doc)
    assert [s["heading"] for s in sections] == ["", "Alpha", "Beta"]
    assert sections[0]["text"].strip() == "intro line"
    assert sections[1]["text"].startswith("# Alpha")
    assert "alpha body" in sections[1]["text"]


def test_heading_inside_code_fence_does_not_split():
    doc = "# Real\nbefore\n```\n# not a heading\nstill code\n```\nafter\n"
    sections = split_sections(doc)
    assert len(sections) == 1
    assert "# not a heading" in sections[0]["text"]


def test_tilde_fence_also_respected():
    doc = "# Real\n~~~\n## fenced\n~~~\ntail\n"
    assert len(split_sections(doc)) == 1


def test_mismatched_fence_marker_does_not_close_fence():
    doc = "# Real\n```\n~~~\n# still fenced\n```\n\n# After\nbody\n"
    sections = split_sections(doc)
    assert [s["heading"] for s in sections] == ["Real", "After"]


def test_fence_with_language_tag_opens_fence():
    doc = "# Real\n```python\n# comment not heading\n```\ndone\n"
    assert len(split_sections(doc)) == 1


def test_heading_only_document():
    sections = split_sections("# Lonely\n")
    assert len(sections) == 1
    assert sections[0]["heading"] == "Lonely"


def test_empty_document():
    assert split_sections("") == []
    assert split_sections("   \n  \n") == []


# ── chunk_text ──────────────────────────────────────────────────────────────

def test_small_sections_merge_into_one_chunk():
    doc = "# A\nshort a\n\n# B\nshort b\n"
    chunks = chunk_text(doc)
    assert len(chunks) == 1
    assert chunks[0]["heading"] == "A"
    assert "short a" in chunks[0]["text"] and "short b" in chunks[0]["text"]


def test_sections_split_when_cap_would_be_exceeded():
    a = "# A\n" + " ".join(["alpha"] * 300)
    b = "# B\n" + " ".join(["beta"] * 300)
    chunks = chunk_text(a + "\n" + b + "\n")
    assert len(chunks) == 2
    assert chunks[0]["heading"] == "A"
    assert chunks[1]["heading"] == "B"
    assert "beta" not in chunks[0]["text"]


def test_oversized_section_falls_back_to_word_window():
    doc = "# Big\n" + " ".join(f"w{i}" for i in range(1200))
    chunks = chunk_text(doc)
    # step = 500 - 50 = 450 -> windows at 0, 450, 900
    assert len(chunks) == 3
    assert all(c["heading"] == "Big" for c in chunks)
    first_words = chunks[0]["text"].split()
    second_words = chunks[1]["text"].split()
    assert first_words[-50:] == second_words[:50]  # overlap preserved


def test_preamble_only_note_gets_empty_heading():
    chunks = chunk_text("just plain text with no headings\n")
    assert len(chunks) == 1
    assert chunks[0]["heading"] == ""


def test_empty_input_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("  \n \n") == []
