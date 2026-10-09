import os
import sys

# Tests import backend modules (retrieval, eval.*) directly, so put the
# backend directory itself on sys.path regardless of where pytest runs from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _fresh_ask_caches():
    """Tests swap main's model/collection/ollama_chat freely; start each one
    with empty Ask caches so no cached answer outlives the test that made it."""
    main = sys.modules.get("main")
    if main is not None:
        main.invalidate_ask_caches()
    yield
