#!/usr/bin/env python3
"""SessionStart hook — implements CLAUDE.md "Session start" protocol.

Injects, in order, the three things every session must begin with:
  1. memory/MEMORY.md  — index of project memory (user profile, conventions, feedback)
  2. wiki/threads.md   — persistent open threads
  3. a lint proposal   — only if .lint/state.yaml shows the auto-lint threshold is crossed
                         (ingests_since_last_lint >= 5 OR last_lint null / > 7 days ago)

The content reaches the model via SessionStart's `additionalContext` (added before the
first prompt). This removes the "I didn't read the session-start files" failure; it
cannot force the agent to *act* on them — that remains a judgment the agent makes.

Fails open: a missing file simply omits that section; a malformed state.yaml omits the
lint proposal. The hook never exits non-zero — a bug here must never block a session.
"""

from __future__ import annotations  # PEP 604 `X | None` annotations on Python 3.9

import datetime
import json
import os
import re
import sys
from pathlib import Path

LINT_INGEST_THRESHOLD = 5
LINT_DAYS_THRESHOLD = 7


def _vault_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _lint_proposal(vault: Path, today: datetime.date | None = None) -> str:
    """Return a one-line lint proposal if the auto-lint threshold is crossed, else ''.

    `today` is injectable so the threshold logic can be unit-tested against a fixed date;
    it defaults to the real clock.
    """
    if today is None:
        today = datetime.date.today()

    text = _read(vault / ".lint" / "state.yaml")
    if not text:
        return ""

    m = re.search(r"ingests_since_last_lint:\s*(\d+)", text)
    ingests = int(m.group(1)) if m else 0

    last_lint = None
    m = re.search(r"last_lint:\s*(\S+)", text)
    if m and m.group(1).lower() not in ("null", "~", "none"):
        # Tolerate a bare date (2026-06-01) or an ISO datetime (2026-06-01T10:00); take the
        # date part. A genuinely unparseable value degrades to None → treated as overdue,
        # which over-proposes lint (safe direction) rather than silently skipping it.
        raw = m.group(1).strip().strip('"\'').split("T")[0]
        try:
            last_lint = datetime.date.fromisoformat(raw)
        except ValueError:
            last_lint = None

    days_stale = None
    overdue_by_time = False
    if last_lint is None:
        overdue_by_time = True
    else:
        days_stale = (today - last_lint).days
        overdue_by_time = days_stale > LINT_DAYS_THRESHOLD

    if ingests >= LINT_INGEST_THRESHOLD or overdue_by_time:
        when = "never" if last_lint is None else f"{last_lint.isoformat()} ({days_stale}d ago)"
        return (
            f"\n## Lint due\n\n"
            f"{ingests} ingest(s) since last lint; last lint: {when}. "
            f"Propose running vault-linter before proceeding. Do not run without confirmation.\n"
        )
    return ""


def main() -> int:
    # Drain stdin defensively (SessionStart carries `source`/`session_id`; we don't need them).
    try:
        sys.stdin.read()
    except OSError:
        pass

    vault = _vault_root()
    parts = []

    memory = _read(vault / "memory" / "MEMORY.md")
    if memory:
        parts.append("# Session start — memory/MEMORY.md\n\n" + memory.strip())

    threads = _read(vault / "wiki" / "threads.md")
    if threads:
        parts.append("# Session start — wiki/threads.md\n\n" + threads.strip())

    proposal = _lint_proposal(vault)
    if proposal:
        parts.append(proposal.strip())

    if not parts:
        return 0

    context = "\n\n---\n\n".join(parts)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open — never block a session on a hook bug
