from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "chat_archiver.py"
SPEC = importlib.util.spec_from_file_location("chat_archiver", MODULE_PATH)
assert SPEC and SPEC.loader
chat_archiver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chat_archiver
SPEC.loader.exec_module(chat_archiver)


def write_jsonl(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in items), encoding="utf-8")


class ChatArchiverTests(unittest.TestCase):
    def test_gemini_uses_visible_content_not_thinking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".gemini" / "antigravity" / "brain"
            transcript = root / "session-1" / ".system_generated" / "logs" / "transcript.jsonl"
            write_jsonl(
                transcript,
                [
                    {
                        "type": "USER_INPUT",
                        "source": "USER_EXPLICIT",
                        "content": "Hello",
                        "created_at": "2026-07-17T12:00:00-07:00",
                    },
                    {
                        "type": "PLANNER_RESPONSE",
                        "source": "MODEL",
                        "content": "Visible answer",
                        "thinking": "private reasoning",
                        "created_at": "2026-07-17T12:00:01-07:00",
                    },
                ],
            )
            scan = chat_archiver.scan_gemini(root, {date(2026, 7, 17)})
            text = "\n".join(message.text for message in scan.sessions[0].messages)
            self.assertIn("Visible answer", text)
            self.assertNotIn("private reasoning", text)

    def test_codex_uses_visible_messages_and_skips_subagent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".codex" / "sessions"
            write_jsonl(
                root / "root.jsonl",
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-17T12:00:00-07:00",
                        "payload": {"session_id": "root", "thread_source": "user"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-17T12:01:00-07:00",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Question"}],
                        },
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-17T12:02:00-07:00",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Answer"}],
                        },
                    },
                ],
            )
            write_jsonl(
                root / "subagent.jsonl",
                [
                    {
                        "type": "session_meta",
                        "timestamp": "2026-07-17T12:00:00-07:00",
                        "payload": {"session_id": "sub", "thread_source": "subagent"},
                    },
                    {
                        "type": "response_item",
                        "timestamp": "2026-07-17T12:01:00-07:00",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Internal"}],
                        },
                    },
                ],
            )
            scan = chat_archiver.scan_codex(root, {date(2026, 7, 17)})
            self.assertEqual([session.session_id for session in scan.sessions], ["root"])
            self.assertEqual([message.text for message in scan.sessions[0].messages], ["Question", "Answer"])

    def test_chatgpt_export_reconstructs_current_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            export = Path(directory) / "conversations.json"
            export.write_text(
                json.dumps(
                    [
                        {
                            "id": "chat-1",
                            "current_node": "assistant",
                            "mapping": {
                                "user": {
                                    "parent": None,
                                    "message": {
                                        "author": {"role": "user"},
                                        "create_time": 1784314800,
                                        "content": {"parts": ["Exported question"]},
                                    },
                                },
                                "assistant": {
                                    "parent": "user",
                                    "message": {
                                        "author": {"role": "assistant"},
                                        "create_time": 1784314860,
                                        "content": {"parts": ["Exported answer"]},
                                    },
                                },
                            },
                        }
                    ]
                ),
                encoding="utf-8",
            )
            target = chat_archiver.parse_timestamp(1784314800).date()
            scan = chat_archiver.scan_chatgpt_export(export, {target})
            self.assertEqual(len(scan.sessions), 1)
            self.assertEqual(len(scan.sessions[0].messages), 2)


if __name__ == "__main__":
    unittest.main()
