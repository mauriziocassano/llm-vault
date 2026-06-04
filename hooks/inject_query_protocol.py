#!/usr/bin/env python3
"""UserPromptSubmit hook — injects the CLAUDE.md QUERY read-protocol.

The QUERY operation requires reading compass.md → index.md → relevant views →
pages/sources before answering, and citing every claim. This is a judgment-based rule
a hook cannot hard-enforce; the best a hook can do is put the protocol in front of the
agent at the moment a question arrives, via UserPromptSubmit `additionalContext`.

Inject-by-default, with a SUPPRESS denylist: when the prompt clearly *starts an
operation* (a slash command or a named operation verb), the QUERY protocol does not
apply and would mislead ("answer only from vault, cite everything" during an ingest),
so we skip injection. The denylist keys on CLAUDE.md's seven operations, which have
stable named triggers — far more robust than trying to detect "is this a question."

By-design trade-off: this is a denylist of *operations*, not a classifier of *questions*.
Only unambiguous operation triggers are suppressed (slash commands, ingest/fetch/forget/
lint/reflect) — ones where the read-and-cite protocol would actively conflict with the
operation. Ambiguous VIEW verbs (compare/draft/make a/timeline/slides) are intentionally
NOT suppressed: they collide with genuine questions, and a VIEW reads vault content anyway,
so a stray injection there is harmless and self-gated ("If this prompt is a question…").
The injected text self-gating means an over-injection is cheap; an over-suppression of a
real question is the costlier error, so the list errs toward injecting.

Fails open: malformed stdin → exit 0 (no injection).
"""

from __future__ import annotations  # safe modern annotations on Python 3.9

import json
import sys

# Prompts that START with any of these are operations, not queries → suppress injection.
# Kept in sync with CLAUDE.md's seven operations and slash commands.
# Only UNAMBIGUOUS operation triggers belong here — ones where injecting "answer only from
# the vault, cite everything" would actively conflict with the operation (you don't cite
# sources while fetching URLs or ingesting). Ambiguous VIEW verbs (compare / draft / make a /
# timeline / slides) are deliberately NOT suppressed: they collide with genuine questions
# ("compare wedge D and E"), and since VIEW also reads vault content first, a stray injection
# on a real view request is harmless and self-gated. Dropping them fixes the false-suppression
# of question-shaped prompts at no real cost.
SUPPRESS_PREFIXES = (
    "/save", "/view", "/reflect", "/forget",
    "ingest", "process inbox", "process the inbox", "fetch",
    "forget", "remove source", "build a view",
    "reflect", "lint", "check the vault", "vault health",
)

QUERY_PROTOCOL = (
    "# QUERY read-protocol (CLAUDE.md)\n\n"
    "If this prompt is a question about the vault, follow this before answering — do not "
    "answer from memory or stale context:\n\n"
    "1. Read `wiki/compass.md` — vault direction and current blind spots.\n"
    "2. Check `wiki/index.md` for relevant pages.\n"
    "3. If a relevant view exists in `wiki/views/`, read it (pre-compiled, often faster).\n"
    "4. Read the relevant pages and sources.\n"
    "5. Answer using only claims traceable in the vault. Cite everything.\n"
    "6. If the vault isn't enough, say so — don't fill gaps with training data.\n"
    "7. If an insight emerges, propose saving it as a new page or view.\n"
)


def main() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except (ValueError, OSError):
        return 0  # fail open

    prompt = data.get("prompt", "")
    if not isinstance(prompt, str):
        return 0

    normalized = prompt.strip().lower()
    if normalized.startswith(SUPPRESS_PREFIXES):
        return 0  # operation, not a query — suppress

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": QUERY_PROTOCOL,
        }
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
