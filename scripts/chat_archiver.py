#!/usr/bin/env python3
"""Archive local AI coding transcripts into an Obsidian vault.

The collector intentionally reads only local, documented-on-disk session files. Cloud
conversation history from ChatGPT, Claude, or Gemini is not scraped from desktop app
caches. Those services require an explicit export/import source.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


PROVIDER_LABELS = {
    "gemini": "Gemini",
    "codex": "Codex",
    "claude-code": "Claude",
    "chatgpt-export": "GPT",
    "claude-export": "Claude",
}
DEFAULT_PROVIDERS = tuple(PROVIDER_LABELS)
MAX_MESSAGE_CHARS = 200_000


@dataclass(frozen=True)
class Message:
    role: str
    text: str
    timestamp: datetime | None


@dataclass
class Session:
    provider: str
    session_id: str
    source: str
    messages: list[Message]


@dataclass
class ProviderScan:
    provider: str
    available: bool
    files_scanned: int
    sessions: list[Session]
    warnings: list[str]


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value)).astimezone()
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.astimezone()
        return parsed.astimezone()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


def extract_text(value: Any) -> str:
    """Return visible text while ignoring thinking and tool payload blocks."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in {
                "text",
                "input_text",
                "output_text",
            }:
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n\n".join(parts)
    if isinstance(value, dict):
        return extract_text(value.get("text") or value.get("content"))
    return ""


def clean_text(value: Any) -> str:
    text = extract_text(value).replace("\x00", "").strip()
    text = re.sub(
        r"(?is)<(?:ADDITIONAL_METADATA|system-reminder)>.*?</(?:ADDITIONAL_METADATA|system-reminder)>",
        "",
        text,
    )
    text = text.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "")
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    if len(text) > MAX_MESSAGE_CHARS:
        text = f"{text[:MAX_MESSAGE_CHARS]}\n\n[truncated by Second Brain archiver]"
    return text


def iter_jsonl(path: Path, warnings: list[str]) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as source:
            for line_number, line in enumerate(source, start=1):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    warnings.append(f"Skipped malformed JSON in {path.name}:{line_number}")
                    continue
                if isinstance(item, dict):
                    yield item
    except OSError as error:
        warnings.append(f"Could not read {path}: {error}")


def recently_modified(path: Path, target_dates: set[date]) -> bool:
    if not target_dates:
        return True
    earliest = min(target_dates)
    cutoff = datetime.combine(earliest - timedelta(days=1), datetime.min.time()).astimezone()
    try:
        return path.stat().st_mtime >= cutoff.timestamp()
    except OSError:
        return False


def add_message(
    messages: list[Message],
    role: str,
    content: Any,
    timestamp_value: Any,
    target_dates: set[date],
) -> None:
    timestamp = parse_timestamp(timestamp_value)
    if timestamp is None or timestamp.date() not in target_dates:
        return
    text = clean_text(content)
    if role == "User" and re.match(
        r"^<(?:environment_context|recommended_plugins|system_context|permissions)>",
        text,
        re.IGNORECASE,
    ):
        return
    if text:
        messages.append(Message(role=role, text=text, timestamp=timestamp))


def scan_gemini(root: Path, target_dates: set[date]) -> ProviderScan:
    warnings: list[str] = []
    sessions: list[Session] = []
    roots = [root]
    if root.name == "brain" and root.parent.name == "antigravity":
        roots.append(root.parent.parent / "antigravity-cli" / "brain")
    available_roots = [candidate for candidate in roots if candidate.is_dir()]
    if not available_roots:
        return ProviderScan(
            "gemini", False, 0, [], [f"Gemini/Antigravity sources not found: {', '.join(map(str, roots))}"]
        )

    files = sorted(
        path
        for candidate in available_roots
        for path in candidate.glob("*/.system_generated/logs/transcript.jsonl")
    )
    scanned = 0
    for path in files:
        if not recently_modified(path, target_dates):
            continue
        scanned += 1
        messages: list[Message] = []
        for item in iter_jsonl(path, warnings):
            item_type = item.get("type")
            source = item.get("source")
            if item_type == "USER_INPUT" and source == "USER_EXPLICIT":
                add_message(messages, "User", item.get("content"), item.get("created_at"), target_dates)
            elif item_type in {"PLANNER_RESPONSE", "GENERIC"} and source == "MODEL":
                # Deliberately exclude the `thinking` field.
                add_message(messages, "Assistant", item.get("content"), item.get("created_at"), target_dates)
        if messages:
            sessions.append(Session("gemini", path.parents[2].name, path.name, messages))
    return ProviderScan("gemini", True, scanned, sessions, warnings)


def scan_codex(root: Path, target_dates: set[date]) -> ProviderScan:
    warnings: list[str] = []
    sessions: list[Session] = []
    roots = [root, root.parent / "archived_sessions"]
    available_roots = [candidate for candidate in roots if candidate.is_dir()]
    if not available_roots:
        return ProviderScan("codex", False, 0, [], [f"Codex sources not found: {root.parent}"])

    scanned = 0
    files = sorted(path for candidate in available_roots for path in candidate.rglob("*.jsonl"))
    for path in files:
        if not recently_modified(path, target_dates):
            continue
        scanned += 1
        session_id = path.stem
        is_subagent = False
        messages: list[Message] = []
        for item in iter_jsonl(path, warnings):
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            if item.get("type") == "session_meta":
                session_id = str(payload.get("session_id") or payload.get("id") or session_id)
                thread_source = payload.get("thread_source")
                source = payload.get("source")
                is_subagent = thread_source == "subagent" or (
                    isinstance(thread_source, dict) and "subagent" in thread_source
                ) or (isinstance(source, dict) and "subagent" in source)
                continue
            if item.get("type") != "response_item" or payload.get("type") != "message":
                continue
            role = payload.get("role")
            if role == "user":
                add_message(messages, "User", payload.get("content"), item.get("timestamp"), target_dates)
            elif role == "assistant":
                add_message(messages, "Assistant", payload.get("content"), item.get("timestamp"), target_dates)
        if messages and not is_subagent:
            sessions.append(Session("codex", session_id, path.name, messages))
    return ProviderScan("codex", True, scanned, sessions, warnings)


def scan_claude_code(root: Path, target_dates: set[date]) -> ProviderScan:
    warnings: list[str] = []
    sessions: list[Session] = []
    if not root.is_dir():
        return ProviderScan("claude-code", False, 0, [], [f"Claude Code source not found: {root}"])

    scanned = 0
    for path in sorted(root.rglob("*.jsonl")):
        if "subagents" in path.parts or not recently_modified(path, target_dates):
            continue
        scanned += 1
        session_id = path.stem
        messages: list[Message] = []
        for item in iter_jsonl(path, warnings):
            if item.get("isSidechain") is True or item.get("isMeta") is True:
                continue
            item_type = item.get("type")
            if item_type not in {"user", "assistant"}:
                continue
            if item_type == "user" and (
                item.get("sourceToolAssistantUUID") or item.get("toolUseResult")
            ):
                continue
            session_id = str(item.get("sessionId") or session_id)
            message = item.get("message")
            content = message.get("content") if isinstance(message, dict) else message
            role = "User" if item_type == "user" else "Assistant"
            add_message(messages, role, content, item.get("timestamp"), target_dates)
        if messages:
            sessions.append(Session("claude-code", session_id, path.name, messages))
    return ProviderScan("claude-code", True, scanned, sessions, warnings)


def export_json_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".json":
        return [root]
    if root.is_dir():
        preferred = root / "conversations.json"
        return [preferred] if preferred.is_file() else sorted(root.glob("*.json"))
    return []


def load_json(path: Path, warnings: list[str]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as error:
        warnings.append(f"Could not read export {path}: {error}")
        return None


def chatgpt_branch(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        return []
    current = conversation.get("current_node")
    branch: list[dict[str, Any]] = []
    visited: set[str] = set()
    while isinstance(current, str) and current in mapping and current not in visited:
        visited.add(current)
        node = mapping[current]
        if not isinstance(node, dict):
            break
        branch.append(node)
        current = node.get("parent")
    if branch:
        return list(reversed(branch))
    return sorted(
        (node for node in mapping.values() if isinstance(node, dict)),
        key=lambda node: ((node.get("message") or {}).get("create_time") or 0),
    )


def scan_chatgpt_export(root: Path, target_dates: set[date]) -> ProviderScan:
    warnings: list[str] = []
    sessions: list[Session] = []
    files = export_json_files(root)
    if not files:
        return ProviderScan(
            "chatgpt-export", False, 0, [], [f"ChatGPT export not found: {root}"]
        )
    for path in files:
        payload = load_json(path, warnings)
        if not isinstance(payload, list):
            warnings.append(f"ChatGPT export is not a conversation list: {path}")
            continue
        for conversation in payload:
            if not isinstance(conversation, dict):
                continue
            messages: list[Message] = []
            for node in chatgpt_branch(conversation):
                message = node.get("message")
                if not isinstance(message, dict):
                    continue
                author = message.get("author")
                role = author.get("role") if isinstance(author, dict) else None
                if role not in {"user", "assistant"}:
                    continue
                content = message.get("content")
                parts = content.get("parts") if isinstance(content, dict) else content
                add_message(
                    messages,
                    "User" if role == "user" else "Assistant",
                    parts,
                    message.get("create_time"),
                    target_dates,
                )
            if messages:
                sessions.append(
                    Session(
                        "chatgpt-export",
                        str(conversation.get("id") or conversation.get("conversation_id") or "chatgpt"),
                        path.name,
                        messages,
                    )
                )
    return ProviderScan("chatgpt-export", True, len(files), sessions, warnings)


def scan_claude_export(root: Path, target_dates: set[date]) -> ProviderScan:
    warnings: list[str] = []
    sessions: list[Session] = []
    files = export_json_files(root)
    if not files:
        return ProviderScan(
            "claude-export", False, 0, [], [f"Claude export not found: {root}"]
        )
    for path in files:
        payload = load_json(path, warnings)
        if not isinstance(payload, list):
            warnings.append(f"Claude export is not a conversation list: {path}")
            continue
        for conversation in payload:
            if not isinstance(conversation, dict):
                continue
            messages: list[Message] = []
            chat_messages = conversation.get("chat_messages")
            if not isinstance(chat_messages, list):
                continue
            for message in chat_messages:
                if not isinstance(message, dict) or message.get("sender") not in {"human", "assistant"}:
                    continue
                content = message.get("text") or message.get("content")
                add_message(
                    messages,
                    "User" if message.get("sender") == "human" else "Assistant",
                    content,
                    message.get("created_at") or message.get("updated_at"),
                    target_dates,
                )
            if messages:
                sessions.append(
                    Session(
                        "claude-export",
                        str(conversation.get("uuid") or conversation.get("id") or "claude"),
                        path.name,
                        messages,
                    )
                )
    return ProviderScan("claude-export", True, len(files), sessions, warnings)


def resolve_source_roots(home: Path, overrides: list[str]) -> dict[str, Path]:
    chatgpt_import = home / "SecondBrainImports" / "ChatGPT"
    claude_import = home / "SecondBrainImports" / "Claude"
    if not chatgpt_import.exists() and (home / "Documents" / "ChatGPTExport").exists():
        chatgpt_import = home / "Documents" / "ChatGPTExport"
    if not claude_import.exists() and (home / "Documents" / "ClaudeExport").exists():
        claude_import = home / "Documents" / "ClaudeExport"
    roots = {
        "gemini": home / ".gemini" / "antigravity" / "brain",
        "codex": home / ".codex" / "sessions",
        "claude-code": home / ".claude" / "projects",
        "chatgpt-export": chatgpt_import,
        "claude-export": claude_import,
    }
    for override in overrides:
        if "=" not in override:
            raise ValueError(f"Source override must use provider=path: {override}")
        provider, raw_path = override.split("=", 1)
        provider = provider.strip().lower()
        if provider not in roots:
            raise ValueError(f"Unknown source provider: {provider}")
        roots[provider] = Path(raw_path).expanduser().resolve()
    return roots


def resolve_vault(explicit: str | None, home: Path) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()

    candidates: list[Path] = []
    for variable in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / "Documents" / "Obsidian Vault")
    candidates.extend(
        [
            home / "Library" / "CloudStorage" / "OneDrive-Personal" / "Documents" / "Obsidian Vault",
            home / "OneDrive" / "Documents" / "Obsidian Vault",
            home / "Documents" / "Obsidian Vault",
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("Obsidian vault not found; pass --vault or set OBSIDIAN_VAULT_PATH")


def default_status_file(home: Path) -> Path:
    if sys.platform == "darwin":
        return home / "Library" / "Logs" / "SecondBrain" / "chat-archiver-status.json"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local_app_data:
        return Path(local_app_data) / "SecondBrain" / "chat-archiver-status.json"
    return home / ".local" / "state" / "second-brain" / "chat-archiver-status.json"


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned or "unknown-machine"


def atomic_write(path: Path, content: str, attempts: int = 5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for attempt in range(attempts):
        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                output.write(content)
            os.replace(temporary, path)
            return
        except OSError as error:
            last_error = error
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            time.sleep(0.25 * (2**attempt))
    assert last_error is not None
    raise last_error


def render_archive(provider: str, target_date: date, machine: str, sessions: list[Session]) -> str:
    label = PROVIDER_LABELS[provider]
    message_count = sum(len(session.messages) for session in sessions)
    lines = [
        "---",
        f'title: "{label} Chat Archive — {target_date.isoformat()} — {machine}"',
        f"date: {target_date.isoformat()}",
        f"provider: {provider}",
        f'machine: "{machine}"',
        f"source_sessions: {len(sessions)}",
        f"message_count: {message_count}",
        f"tags: [ai-chats, {provider}, daily-archive, imported]",
        "---",
        "",
        f"# {label} Chat Archive — {target_date.isoformat()}",
        "",
        f"Captured from local session files on `{machine}`.",
        "",
    ]
    for session in sorted(sessions, key=lambda item: item.session_id):
        lines.extend([f"## Session `{session.session_id[:12]}`", ""])
        for message in session.messages:
            timestamp = message.timestamp.strftime("%H:%M:%S %Z") if message.timestamp else "time unknown"
            lines.extend([f"### {message.role} — {timestamp}", "", message.text, ""])
        lines.extend(["---", ""])
    return "\n".join(lines).rstrip() + "\n"


def trigger_reindex(url: str) -> str | None:
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if response.status >= 300:
                return f"RAG re-index request returned HTTP {response.status}"
    except Exception as error:  # The archiver must still succeed if the local app is offline.
        return f"RAG re-index request failed: {error}"
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", help="Absolute Obsidian vault path")
    parser.add_argument("--date", help="Archive one local date (YYYY-MM-DD)")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=1,
        help="Number of dates to archive, including today (default: 1)",
    )
    parser.add_argument(
        "--providers",
        default=",".join(DEFAULT_PROVIDERS),
        help="Comma-separated providers or 'all': gemini,codex,claude-code,chatgpt-export,claude-export",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="PROVIDER=PATH",
        help="Override a provider's local session root",
    )
    parser.add_argument("--status-file", help="JSON run-status destination")
    parser.add_argument("--machine", help="Machine label used in archive filenames")
    parser.add_argument("--reindex-url", help="POST this URL after writing archives")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = datetime.now().astimezone()
    home = Path.home()
    status_path = Path(args.status_file).expanduser() if args.status_file else default_status_file(home)
    machine = safe_name(args.machine or socket.gethostname() or platform.node())
    status: dict[str, Any] = {
        "started_at": started.isoformat(),
        "finished_at": None,
        "success": False,
        "dry_run": args.dry_run,
        "machine": machine,
        "vault": None,
        "dates": [],
        "providers": {},
        "archives": [],
        "warnings": [],
        "error": None,
    }

    try:
        if args.date:
            target_dates = {date.fromisoformat(args.date)}
        else:
            if args.lookback_days < 1 or args.lookback_days > 31:
                raise ValueError("--lookback-days must be between 1 and 31")
            today = date.today()
            target_dates = {today - timedelta(days=offset) for offset in range(args.lookback_days)}
        status["dates"] = sorted(item.isoformat() for item in target_dates)

        selected = [item.strip().lower() for item in args.providers.split(",") if item.strip()]
        if selected == ["all"]:
            selected = list(PROVIDER_LABELS)
        unknown = sorted(set(selected) - set(PROVIDER_LABELS))
        if unknown:
            raise ValueError(f"Unknown provider(s): {', '.join(unknown)}")

        vault = resolve_vault(args.vault, home)
        if not vault.is_dir():
            raise FileNotFoundError(f"Obsidian vault does not exist: {vault}")
        status["vault"] = str(vault)
        roots = resolve_source_roots(home, args.source)

        scanners = {
            "gemini": scan_gemini,
            "codex": scan_codex,
            "claude-code": scan_claude_code,
            "chatgpt-export": scan_chatgpt_export,
            "claude-export": scan_claude_export,
        }
        scans = [scanners[provider](roots[provider], target_dates) for provider in selected]

        for scan in scans:
            status["providers"][scan.provider] = {
                "available": scan.available,
                "files_scanned": scan.files_scanned,
                "sessions_archived": len(scan.sessions),
                "messages_archived": sum(len(session.messages) for session in scan.sessions),
            }
            status["warnings"].extend(scan.warnings)
            for target_date in sorted(target_dates):
                sessions: list[Session] = []
                for session in scan.sessions:
                    messages = [
                        message
                        for message in session.messages
                        if message.timestamp is not None and message.timestamp.date() == target_date
                    ]
                    if messages:
                        sessions.append(
                            Session(session.provider, session.session_id, session.source, messages)
                        )
                if not sessions:
                    continue
                label = PROVIDER_LABELS[scan.provider]
                destination = (
                    vault
                    / "05 AI Chats"
                    / label
                    / "Coding"
                    / f"{target_date.isoformat()} - Daily {scan.provider} Chat Archive - {machine}.md"
                )
                archive = render_archive(scan.provider, target_date, machine, sessions)
                if not args.dry_run:
                    atomic_write(destination, archive)
                status["archives"].append(
                    {
                        "provider": scan.provider,
                        "date": target_date.isoformat(),
                        "path": str(destination),
                        "sessions": len(sessions),
                        "messages": sum(len(session.messages) for session in sessions),
                    }
                )

        if status["archives"] and args.reindex_url and not args.dry_run:
            warning = trigger_reindex(args.reindex_url)
            if warning:
                status["warnings"].append(warning)

        status["success"] = True
        print(
            f"Second Brain archive complete: {len(status['archives'])} note(s), "
            f"{sum(item['messages'] for item in status['archives'])} message(s)."
        )
        for warning in status["warnings"]:
            print(f"Warning: {warning}", file=sys.stderr)
        return_code = 0
    except Exception as error:
        status["error"] = str(error)
        print(f"Second Brain archive failed: {error}", file=sys.stderr)
        return_code = 1
    finally:
        status["finished_at"] = datetime.now().astimezone().isoformat()
        try:
            atomic_write(status_path, json.dumps(status, indent=2, sort_keys=True) + "\n")
        except OSError as error:
            print(f"Could not write status file {status_path}: {error}", file=sys.stderr)
            return_code = 1
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
