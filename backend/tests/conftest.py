import os
import sys

# Tests import backend modules (retrieval, eval.*) directly, so put the
# backend directory itself on sys.path regardless of where pytest runs from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pytest


@pytest.fixture(autouse=True)
def _no_background_health_scans(monkeypatch):
    """A real health scan writes health_cache.json into the working directory,
    which is the live backend's cache when pytest runs from backend/. Tests
    that exercise the trigger stub or capture start_health_scan themselves."""
    main = sys.modules.get("main")
    if main is not None and hasattr(main, "start_health_scan"):
        monkeypatch.setattr(main, "start_health_scan", lambda reason: False)
