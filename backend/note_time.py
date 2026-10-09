"""When a note "happened", for recency ranking.

File mtime alone is noisy in this vault: a bulk rewrite (re-import, sync,
an archiver pass) stamps hundreds of old chats with the same new mtime. Chat
exports and many notes carry their real date at the front of the file name
("2026-07-20 - AI Eval Harness Setup.md"), so that date wins when present;
anything else falls back to the mtime the indexer stamped on the chunk.
"""
import calendar
import re

_LEADING_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?!\d)")


def note_timestamp(source, mtime):
    """Epoch seconds for the note: its file-name date (noon UTC) or its mtime; None if neither."""
    name = (source or "").replace("\\", "/").rsplit("/", 1)[-1]
    m = _LEADING_DATE.match(name)
    if m:
        year, month, day = (int(g) for g in m.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return float(calendar.timegm((year, month, day, 12, 0, 0)))
            except (ValueError, OverflowError):
                pass
    if isinstance(mtime, (int, float)):
        return float(mtime)
    return None
