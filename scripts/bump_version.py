#!/usr/bin/env python3
"""Bump SENA package version from a single source of truth."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT_FILE = ROOT / "src" / "sena" / "__init__.py"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"
VERSION_RE = re.compile(r'__version__\s*=\s*"(?P<version>\d+\.\d+\.\d+)"')
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _read_current_version() -> str:
    match = VERSION_RE.search(INIT_FILE.read_text())
    if not match:
        raise SystemExit(f"Could not find __version__ assignment in {INIT_FILE}")
    return match.group("version")


def _write_new_version(new_version: str) -> None:
    contents = INIT_FILE.read_text()
    updated, count = VERSION_RE.subn(f'__version__ = "{new_version}"', contents, count=1)
    if count != 1:
        raise SystemExit("Failed to update __version__; expected exactly one match")
    INIT_FILE.write_text(updated)


def _update_changelog(new_version: str) -> None:
    today = __import__("datetime").date.today().isoformat()
    marker = "## [Unreleased]"
    text = CHANGELOG_FILE.read_text()
    if marker not in text:
        raise SystemExit("CHANGELOG.md is missing '## [Unreleased]' section")
    replacement = f"{marker}\n\n## [{new_version}] - {today}"
    CHANGELOG_FILE.write_text(text.replace(marker, replacement, 1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump package version")
    parser.add_argument("new_version", help="Target semantic version (e.g., 0.3.1)")
    parser.add_argument(
        "--update-changelog",
        action="store_true",
        help="Move Unreleased notes under the new version heading",
    )
    args = parser.parse_args()

    if not SEMVER_RE.fullmatch(args.new_version):
        raise SystemExit("new_version must be a semantic version formatted as X.Y.Z")

    current = _read_current_version()
    if current == args.new_version:
        raise SystemExit(f"Version is already {args.new_version}")

    _write_new_version(args.new_version)
    if args.update_changelog:
        _update_changelog(args.new_version)

    print(f"Updated version: {current} -> {args.new_version}")


if __name__ == "__main__":
    main()
