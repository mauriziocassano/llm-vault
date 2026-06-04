#!/usr/bin/env python3
"""PostToolUse(Edit|Write) hook — nudges CLAUDE.md invariant #6 after a wiki write.

Invariant #6: update wiki/index.md AND wiki/log.md after any writing operation. This is
a cross-turn obligation, so it can't be hard-gated on a single tool call. When the agent
writes a compiled wiki file (pages/sources/views), this hook injects a reminder via
PostToolUse `additionalContext` — visible to the model at the moment of the write, where
it's actionable. (A Stop-hook block was rejected: its `reason` goes to the user, not the
model, and there is no loop guard.) The vault-linter remains the deterministic backstop.

Writes to index.md / log.md themselves don't trigger the reminder (no self-nagging).

Always exits 0; never blocks. Fails open on malformed stdin or a non-wiki path.
"""

from __future__ import annotations  # safe modern annotations on Python 3.9

import json
import os
import sys
from pathlib import Path

# Compiled-content subdirs whose writes carry the invariant-#6 obligation.
CONTENT_SUBDIRS = ("pages", "sources", "views")


def _vault_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except (ValueError, OSError):
        return 0

    tool_input = data.get("tool_input")
    file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
    if not file_path:
        return 0

    vault = _vault_root()
    try:
        target = Path(file_path).resolve()
    except (OSError, ValueError):
        return 0

    # Two-stage gate. Stage 1 (here) only excludes paths *outside* wiki/; stage 2 (the
    # CONTENT_SUBDIRS check below) is what actually narrows to compiled content. So a
    # root-level wiki file like compass.md/threads.md passes stage 1 but is dropped by
    # stage 2 — by design (those carry no invariant-#6 obligation).
    wiki_dir = (vault / "wiki").resolve()
    if wiki_dir not in target.parents:
        return 0  # not a wiki write

    # Suppress when the write IS index.md or log.md — those are the satisfying actions.
    if target.name in ("index.md", "log.md") and target.parent == wiki_dir:
        return 0

    # Only nudge for compiled-content writes (pages/sources/views).
    rel_parts = target.relative_to(wiki_dir).parts
    if not rel_parts or rel_parts[0] not in CONTENT_SUBDIRS:
        return 0

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"Invariant #6: you wrote `wiki/{'/'.join(rel_parts)}`. Before finishing this "
                "operation, update `wiki/index.md` (entry + format) and append to `wiki/log.md`."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
