#!/usr/bin/env python3
"""PreToolUse(Edit|Write) guard — enforces CLAUDE.md invariant #1 (never write to raw/).

`raw/` holds immutable source truth. Only the inbox-fetcher skill adds files there.
This hook hard-blocks any Edit/Write whose target resolves under `raw/` (exit 2 + stderr).

FORGET deletes from `raw/` via `Bash(rm)`, not Edit/Write — that path is sanctioned by
CLAUDE.md (invariant #1 covers *creation*, not user-directed removal) and is correctly
NOT caught here. Do not widen the matcher to Bash.

Fails open: malformed stdin, non-dict tool_input, missing file_path, or a path that
resolves outside the vault → exit 0 (never block legitimate work on a hook bug).
"""

from __future__ import annotations  # safe modern annotations on Python 3.9

import json
import os
import sys
from pathlib import Path


def _vault_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    # Fallback: hooks/ is a direct child of the vault root (symlinked into .claude/hooks,
    # but __file__.resolve() follows the symlink back to the real hooks/ dir).
    return Path(__file__).resolve().parents[1]


try:
    data = json.loads(sys.stdin.read())
except (ValueError, OSError):
    sys.exit(0)  # fail open

# Valid JSON that isn't an object (str/int/list/null) → degrade, don't raise on .get().
if not isinstance(data, dict):
    sys.exit(0)

tool_input = data.get("tool_input")
file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
if not file_path:
    sys.exit(0)

vault = _vault_root()
raw_dir = (vault / "raw").resolve()

try:
    target = Path(file_path).resolve()
except (OSError, ValueError):
    sys.exit(0)

# Block if the target is raw/ itself or anything under it.
if target == raw_dir or raw_dir in target.parents:
    print(
        "BLOCKED: raw/ is immutable (CLAUDE.md invariant #1). Only the inbox-fetcher "
        "writes there; FORGET removes via Bash rm. Edit/Write to raw/ is never allowed.",
        file=sys.stderr,
    )
    sys.exit(2)

sys.exit(0)
