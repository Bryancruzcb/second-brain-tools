"""context_header(): the one-line identity prepended to a chunk under the
context-header scheme. Folder path, note title, section heading."""
from indexer import CONTEXT_HEADER_MAX_CHARS, context_header


def test_nested_path_title_and_heading():
    assert context_header(
        "02 Projects/Data Science Project/decisions.md", "decisions", "is_delayed definition"
    ) == "02 Projects > Data Science Project > decisions > is_delayed definition"


def test_root_note_without_heading_is_just_the_title():
    assert context_header("API KEYS.md", "API KEYS", "") == "API KEYS"


def test_heading_that_repeats_the_title_is_dropped():
    assert context_header("Sourdough Starter.md", "Sourdough Starter", "Sourdough Starter") == "Sourdough Starter"


def test_title_that_repeats_its_folder_is_dropped():
    assert context_header("Foo/Foo.md", "Foo", "Intro") == "Foo > Intro"


def test_whitespace_collapses_to_one_line():
    assert context_header("a/b.md", "b", "  multi\n line\t heading ") == "a > b > multi line heading"


def test_backslash_paths_are_normalised():
    assert context_header("a\\b\\c.md", "c", "") == "a > b > c"


def test_header_is_capped():
    out = context_header("a/b.md", "b", "x" * 500)
    assert len(out) <= CONTEXT_HEADER_MAX_CHARS
    assert out.startswith("a > b > xxx")
