#!/usr/bin/env python3
"""Render launchd plists and the macOS launcher without unsafe shell interpolation."""

from __future__ import annotations

import argparse
import os
import plistlib
import shlex
import tempfile
from pathlib import Path
from typing import Any


def atomic_write(destination: Path, payload: bytes, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
        temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def replace_strings(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        return value
    if isinstance(value, list):
        return [replace_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: replace_strings(item, replacements)
            for key, item in value.items()
        }
    return value


def render_plist(args: argparse.Namespace) -> None:
    with args.source.open("rb") as source:
        payload = plistlib.load(source)

    rendered = replace_strings(
        payload,
        {
            "__PROJECT_ROOT__": str(args.project_root),
            "__USER_HOME__": str(args.user_home),
            "__NODE_PATH__": str(args.node_path),
        },
    )
    encoded = plistlib.dumps(rendered, fmt=plistlib.FMT_XML, sort_keys=False)
    atomic_write(args.destination, encoded, 0o644)


def render_launcher(args: argparse.Namespace) -> None:
    template = args.source.read_text(encoding="utf-8")
    placeholder = "__SECOND_BRAIN_COMMAND__"
    if template.count(placeholder) != 1:
        raise ValueError(f"Launcher template must contain exactly one {placeholder}")

    command = shlex.quote(str(args.project_root / "scripts" / "second-brain"))
    rendered = template.replace(placeholder, command).encode("utf-8")
    atomic_write(args.destination, rendered, 0o755)


def path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def executable_path(value: str) -> Path:
    """Keep stable package-manager symlinks instead of pinning a versioned target."""
    return Path(os.path.abspath(os.path.expanduser(value)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    plist_parser = subparsers.add_parser("plist")
    plist_parser.add_argument("source", type=path)
    plist_parser.add_argument("destination", type=path)
    plist_parser.add_argument("--project-root", type=path, required=True)
    plist_parser.add_argument("--user-home", type=path, required=True)
    plist_parser.add_argument("--node-path", type=executable_path, required=True)
    plist_parser.set_defaults(handler=render_plist)

    launcher_parser = subparsers.add_parser("launcher")
    launcher_parser.add_argument("source", type=path)
    launcher_parser.add_argument("destination", type=path)
    launcher_parser.add_argument("--project-root", type=path, required=True)
    launcher_parser.set_defaults(handler=render_launcher)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
