#!/usr/bin/env python3
"""
record_ingest.py — Increment ingests_since_last_lint in .lint/state.yaml.

Called by the INGEST protocol after every completed ingest operation so the
auto-lint trigger in CLAUDE.md (≥5 ingests or ≥7 days) has accurate data.

Usage:
    python3 record_ingest.py                    # uses cwd as vault
    python3 record_ingest.py --vault /path      # explicit vault root

Exit codes:
    0 — success
    2 — filesystem error
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def record_ingest(vault: Path) -> int:
    state_path = vault / ".lint" / "state.yaml"

    if not state_path.exists():
        state_path.parent.mkdir(exist_ok=True)
        state_path.write_text("ingests_since_last_lint: 1\n", encoding="utf-8")
        print("Created .lint/state.yaml with ingests_since_last_lint: 1")
        return 0

    text = state_path.read_text(encoding="utf-8")

    def bump(m: re.Match) -> str:
        return f"ingests_since_last_lint: {int(m.group(1)) + 1}"

    new_text, n = re.subn(r"ingests_since_last_lint:\s*(\d+)", bump, text)

    if n == 0:
        new_text = text.rstrip("\n") + "\ningests_since_last_lint: 1\n"

    state_path.write_text(new_text, encoding="utf-8")

    m = re.search(r"ingests_since_last_lint:\s*(\d+)", new_text)
    print(f"ingests_since_last_lint → {m.group(1) if m else '?'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a vault ingest in lint state.")
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    args = parser.parse_args()

    try:
        return record_ingest(args.vault)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
