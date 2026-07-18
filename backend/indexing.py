"""Shared, content-first Obsidian indexing for the API and maintenance CLI."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import chromadb


COLLECTION_NAME = "second_brain"
CHUNK_WORDS = 500
CHUNK_OVERLAP = 50
MAX_NOTE_BYTES = 5 * 1024 * 1024
FILE_READ_TIMEOUT_SECONDS = 3.0
MAX_CONCURRENT_READS = 16
EXCLUDED_DIRECTORIES = {
    ".git",
    ".obsidian",
    ".smart-env",
    ".trash",
    "node_modules",
    "Obsidian Vault Backup",
    "99 Import Logs",
    "Templates",
    "06 Exports",
}
SENSITIVE_FILENAMES = {
    "api keys.md",
    "secrets.md",
}


@dataclass(frozen=True)
class IndexRecord:
    record_id: str
    document: str
    metadata: dict[str, str | int | float | bool]


@dataclass
class ScanResult:
    records: list[IndexRecord]
    notes_scanned: int
    notes_skipped: int
    skipped_sources: list[str]
    warnings: list[str]


@dataclass
class IndexSummary:
    vault_path: str
    database_path: str
    notes_scanned: int
    notes_skipped: int
    chunks_indexed: int
    chunks_preserved: int
    warnings: list[str]
    duration_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "vault_path": self.vault_path,
            "database_path": self.database_path,
            "notes_scanned": self.notes_scanned,
            "notes_skipped": self.notes_skipped,
            "chunks_indexed": self.chunks_indexed,
            "chunks_preserved": self.chunks_preserved,
            "warnings": self.warnings,
            "duration_seconds": self.duration_seconds,
        }


def resolve_vault_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()

    home = Path.home()
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
    return next((candidate.resolve() for candidate in candidates if candidate.is_dir()), candidates[0])


def resolve_database_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("SECOND_BRAIN_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent / "chroma_db"


def extract_frontmatter_tags(content: str) -> list[str]:
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return []
    frontmatter = match.group(1)
    inline = re.search(r"^tags:\s*\[([^\]]+)]", frontmatter, re.MULTILINE)
    if inline:
        return [item.strip().strip("\"'").lstrip("#") for item in inline.group(1).split(",")]
    block = re.search(r"^tags:\s*\n((?:\s+-[^\n]+\n?)+)", frontmatter, re.MULTILINE)
    if block:
        return [
            re.sub(r"^\s*-\s*#?", "", line).strip().strip("\"'")
            for line in block.group(1).splitlines()
            if line.strip()
        ]
    return []


def chunk_text(text: str, chunk_words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if chunk_words <= 0 or overlap < 0 or overlap >= chunk_words:
        raise ValueError("chunk_words must be positive and overlap must be smaller")
    words = text.split()
    if not words:
        return []
    step = chunk_words - overlap
    return [" ".join(words[index : index + chunk_words]) for index in range(0, len(words), step)]


def is_cloud_placeholder(path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return True
    # APFS compression can legitimately report zero allocated blocks for a readable
    # file, so st_blocks is not a reliable OneDrive-placeholder test on macOS.
    return bool(getattr(stat, "st_flags", 0) & 0x40000000)


def read_paths_with_timeouts(
    paths: list[Path],
    timeout: float = FILE_READ_TIMEOUT_SECONDS,
    concurrency: int = MAX_CONCURRENT_READS,
) -> dict[Path, tuple[str | None, BaseException | None]]:
    """Read cloud-backed notes concurrently with an independent deadline per file."""
    pending = list(paths)
    running: dict[Path, tuple[threading.Thread, float]] = {}
    outcomes: dict[Path, tuple[str | None, BaseException | None]] = {}
    worker_results: dict[Path, tuple[str | None, BaseException | None]] = {}

    def read(path: Path) -> None:
        try:
            worker_results[path] = (path.read_text(encoding="utf-8"), None)
        except BaseException as error:
            worker_results[path] = (None, error)

    while pending or running:
        while pending and len(running) < concurrency:
            path = pending.pop(0)
            worker = threading.Thread(target=read, args=(path,), name=f"read-{path.name}", daemon=True)
            worker.start()
            running[path] = (worker, time.monotonic())

        now = time.monotonic()
        for path, (worker, started) in list(running.items()):
            if not worker.is_alive():
                outcomes[path] = worker_results.pop(path, (None, OSError("read returned no result")))
                del running[path]
            elif now - started >= timeout:
                outcomes[path] = (None, TimeoutError(f"read timed out after {timeout:g}s"))
                del running[path]
        if running:
            time.sleep(0.02)
    return outcomes


def provider_from_source(source: str) -> str:
    parts = Path(source).parts
    if len(parts) >= 3 and parts[0].lower() == "05 ai chats":
        return parts[1].lower().replace(" ", "-")
    return "obsidian"


def record_id(source: str, chunk_index: int) -> str:
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]
    return f"note-{digest}-{chunk_index:05d}"


def iter_markdown_files(vault_path: Path) -> Iterable[Path]:
    for root, directories, files in os.walk(vault_path):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in EXCLUDED_DIRECTORIES and not directory.startswith(".")
        )
        for filename in sorted(files):
            if filename.endswith(".md") and filename.casefold() not in SENSITIVE_FILENAMES:
                yield Path(root) / filename


def scan_vault(vault_path: Path) -> ScanResult:
    if not vault_path.is_dir():
        raise FileNotFoundError(f"Obsidian vault not found: {vault_path}")

    records: list[IndexRecord] = []
    warnings: list[str] = []
    skipped_sources: list[str] = []
    notes_scanned = 0
    notes_skipped = 0

    readable_candidates: list[Path] = []
    preflight_errors: dict[Path, BaseException] = {}
    for path in iter_markdown_files(vault_path):
        try:
            if path.stat().st_size > MAX_NOTE_BYTES:
                raise OSError(f"note exceeds {MAX_NOTE_BYTES} bytes")
            readable_candidates.append(path)
        except OSError as error:
            preflight_errors[path] = error

    outcomes = read_paths_with_timeouts(readable_candidates)
    for path in [*readable_candidates, *preflight_errors]:
        source = path.relative_to(vault_path).as_posix()
        content, error = outcomes.get(path, (None, preflight_errors.get(path)))
        if error is not None or content is None:
            notes_skipped += 1
            skipped_sources.append(source)
            warnings.append(f"Skipped {source}: {error}")
            continue

        tags = extract_frontmatter_tags(content)
        chunks = chunk_text(content)
        if not chunks:
            chunks = [f"Empty Obsidian note: {path.stem}"]
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        for index, chunk in enumerate(chunks):
            metadata: dict[str, str | int | float | bool] = {
                "source": source,
                "title": path.stem,
                "tags": ",".join(tags),
                "provider": provider_from_source(source),
                "chunk_index": index,
                "content_hash": content_hash,
                "index_kind": "content" if content.strip() else "empty",
            }
            records.append(IndexRecord(record_id(source, index), chunk, metadata))
        notes_scanned += 1

    return ScanResult(records, notes_scanned, notes_skipped, skipped_sources, warnings)


def existing_content_by_source(collection: Any | None) -> dict[str, list[IndexRecord]]:
    if collection is None:
        return {}
    try:
        result = collection.get(include=["documents", "metadatas"])
    except Exception:
        return {}
    grouped: dict[str, list[IndexRecord]] = {}
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    for old_id, document, metadata in zip(ids, documents, metadatas):
        if not isinstance(metadata, dict) or metadata.get("index_kind") not in {"content", "empty"}:
            continue
        source = metadata.get("source")
        if isinstance(source, str) and isinstance(document, str):
            grouped.setdefault(source, []).append(IndexRecord(str(old_id), document, metadata))
    return grouped


def add_records(collection: Any, records: list[IndexRecord], model: Any, batch_size: int = 64) -> None:
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        documents = [record.document for record in batch]
        embeddings = model.encode(documents).tolist()
        collection.add(
            ids=[record.record_id for record in batch],
            documents=documents,
            embeddings=embeddings,
            metadatas=[record.metadata for record in batch],
        )


def swap_collection(client: Any, temporary: Any, collection_name: str) -> Any:
    backup_name = f"{collection_name}_backup_{uuid.uuid4().hex}"
    previous = None
    try:
        previous = client.get_collection(collection_name)
    except Exception:
        previous = None

    if previous is not None:
        previous.modify(name=backup_name)
    try:
        temporary.modify(name=collection_name)
    except Exception:
        if previous is not None:
            previous.modify(name=collection_name)
        raise
    if previous is not None:
        client.delete_collection(backup_name)
    return temporary


def clean_abandoned_builds(client: Any, collection_name: str, keep: str | None = None) -> None:
    prefixes = (f"{collection_name}_build_", f"{collection_name}_backup_")
    for collection in client.list_collections():
        name = collection.name if hasattr(collection, "name") else str(collection)
        if name != keep and name.startswith(prefixes):
            try:
                client.delete_collection(name)
            except Exception:
                pass


def rebuild_index(
    *,
    model: Any,
    vault_path: str | os.PathLike[str] | None = None,
    database_path: str | os.PathLike[str] | None = None,
    collection_name: str = COLLECTION_NAME,
) -> tuple[Any, IndexSummary]:
    started = time.monotonic()
    vault = resolve_vault_path(vault_path)
    database = resolve_database_path(database_path)
    database.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(database))

    try:
        previous = client.get_collection(collection_name)
    except Exception:
        previous = None
    previous_by_source = existing_content_by_source(previous)

    scan = scan_vault(vault)
    preserved: list[IndexRecord] = []
    for source in scan.skipped_sources:
        preserved.extend(previous_by_source.get(source, []))
    records = scan.records + preserved
    if not records:
        raise RuntimeError("No readable Markdown content was found; existing index was left unchanged")

    temporary_name = f"{collection_name}_build_{uuid.uuid4().hex}"
    temporary = client.create_collection(temporary_name)
    try:
        add_records(temporary, records, model)
        if temporary.count() != len(records):
            raise RuntimeError(
                f"Index validation failed: expected {len(records)} records, found {temporary.count()}"
            )
        active = swap_collection(client, temporary, collection_name)
    except Exception:
        try:
            client.delete_collection(temporary_name)
        except Exception:
            pass
        raise
    clean_abandoned_builds(client, collection_name, keep=collection_name)

    summary = IndexSummary(
        vault_path=str(vault),
        database_path=str(database),
        notes_scanned=scan.notes_scanned,
        notes_skipped=scan.notes_skipped,
        chunks_indexed=len(records),
        chunks_preserved=len(preserved),
        warnings=scan.warnings,
        duration_seconds=round(time.monotonic() - started, 3),
    )
    return active, summary
