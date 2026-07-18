from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from indexing import chunk_text, scan_vault


class IndexingTests(unittest.TestCase):
    def test_scan_indexes_real_ai_chat_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            chat = vault / "05 AI Chats" / "Claude" / "Coding" / "session.md"
            chat.parent.mkdir(parents=True)
            chat.write_text(
                "---\ntags: [ai-chats, claude]\n---\nA unique transcript sentence.",
                encoding="utf-8",
            )
            (vault / "API KEYS.md").write_text("secret-key", encoding="utf-8")
            (vault / "SeCrEtS.md").write_text("another-secret", encoding="utf-8")

            result = scan_vault(vault)
            self.assertEqual(result.notes_scanned, 1)
            self.assertTrue(any("unique transcript sentence" in item.document for item in result.records))
            self.assertTrue(all(item.metadata["source"] != "API KEYS.md" for item in result.records))
            self.assertTrue(all(item.metadata["source"] != "SeCrEtS.md" for item in result.records))
            self.assertEqual(result.records[0].metadata["provider"], "claude")
            self.assertEqual(result.records[0].metadata["index_kind"], "content")

    def test_chunking_has_overlap_without_empty_tail(self) -> None:
        words = " ".join(f"word-{index}" for index in range(12))
        chunks = chunk_text(words, chunk_words=5, overlap=2)
        self.assertEqual(len(chunks), 4)
        self.assertIn("word-3", chunks[0])
        self.assertIn("word-3", chunks[1])
        self.assertEqual(chunks[-1].split(), ["word-9", "word-10", "word-11"])


if __name__ == "__main__":
    unittest.main()
