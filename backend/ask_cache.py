"""Process-local LRU caches for the Ask path.

Two caches sit in front of the slow stages of /api/query and
/api/query/stream: one holds the hybrid-retrieval result for a query, the
other the generated answer for an exact prompt. Both are dropped whenever
the index changes (see main.invalidate_ask_caches), and every entry also
expires after ASK_CACHE_TTL_SECONDS, so a missed invalidation can only serve
a stale answer for that long. ASK_CACHE_TTL_SECONDS=0 turns both off.
"""
import threading
import time
from collections import OrderedDict

import config


class TTLCache:
    """A thread-safe LRU of at most ``maxsize`` entries with a per-read TTL."""

    def __init__(self, maxsize):
        self.maxsize = maxsize
        self._entries = OrderedDict()  # key -> (stored_at, value)
        self._lock = threading.Lock()

    def get(self, key):
        """The live value for key, or None on a miss, an expiry, or caching off."""
        ttl = config.get_ask_cache_ttl_seconds()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if ttl <= 0 or time.monotonic() - stored_at > ttl:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return value

    def put(self, key, value):
        if config.get_ask_cache_ttl_seconds() <= 0:
            return
        with self._lock:
            self._entries[key] = (time.monotonic(), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.maxsize:
                self._entries.popitem(last=False)

    def clear(self):
        with self._lock:
            self._entries.clear()

    def __len__(self):
        with self._lock:
            return len(self._entries)
