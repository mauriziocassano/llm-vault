---
description: Cascade-remove a source from the vault. Deletes wiki/sources/<slug>.md and the raw/ file it points to, removes or downgrades citations in wiki/pages/, updates or warns about wiki/views/ that depended on it, updates index.md and log.md, and runs the linter to confirm zero dead links. Never auto-deletes prose — every removed claim is confirmed with the user first.
---

# /forget — Cascade-remove a source

Remove a source and everything that depended only on it, without
leaving dangling citations behind. This is the inverse of INGEST.

## Arguments

`/forget <source>` where `<source>` can be:

- A slug: `/forget agent-skills-spec`
- A wiki path: `/forget wiki/sources/agent-skills-spec.md`
- A raw path: `/forget raw/web/agent-skills-spec/index.md`
- A URL if you remember it (agent resolves to the slug)

If ambiguous, agent lists candidates and asks.

## Protocol

### 1. Resolve target

Find `wiki/sources/<slug>.md` and the `raw/` file it points to via
`source_path`. Confirm with the user: show the title, source_url,
and when it was ingested.

### 2. Map the fanout

Grep the vault for every reference to the source:

- `[[wiki/sources/<slug>]]` in any markdown
- The raw path string (for direct `raw/...` citations)
- The slug in `based_on:` lists of views

List the references for the user, grouped by file type:

```
wiki/pages/   (3 files cite this source)
  - agent-skills.md: 2 citations
  - context-engineering.md: 1 citation
  - claude-code.md: 1 citation
wiki/views/   (1 view depends on this source)
  - timeline-agent-skills.md (shareable: false)
```

If the fanout exceeds **15 files** (invariant #5), stop. Report the
count and let the user choose: full cascade over multiple passes, or
leave citations as dead links for the linter to flag.

### 3. Handle pages

For each `wiki/pages/...` that cites the source, decide per claim:

- **Claim supported by other sources** → drop only this citation.
  The prose stays. One file, one edit.
- **Claim depended only on this source** → propose three options to
  the user:
  - Remove the claim outright.
  - Degrade it to "unverified" (mark with `#unverified` tag).
  - Keep as-is and let the linter flag the dead link (explicit
    acknowledgment that the source is gone but the thought stays).

**Never delete prose without confirmation**, one file at a time.

### 4. Handle views

For each `wiki/views/...` with the source in `based_on`:

- `shareable: false` → rebuild or trim. If trimming empties the view,
  ask whether to delete the view entirely.
- `shareable: true` → do NOT touch. Warn the user the view is now
  partially unsourced and let them decide whether to issue a new
  dated version.

### 5. Delete the source

- Delete `wiki/sources/<slug>.md`.
- Delete the `raw/` file (or directory, for `raw/web/<slug>/`).

This is the one case where removing from `raw/` is allowed —
invariant #1 covers *creation*, not user-directed removal.

### 6. Update bookkeeping

- Remove the entry from `index.md`.
- Append to `log.md`: `## [YYYY-MM-DD] forget <slug>` with a one-line
  summary of what was touched (page count, view count).

### 7. Verify

Run `vault-linter`. Confirm zero new dead links introduced. If any
remain, they're the explicit "acknowledged" ones from step 3 — note
in the final report.

## Report format

End of operation, tell the user:

```
Forgot: <slug>
  ✓ Deleted wiki/sources/<slug>.md
  ✓ Deleted raw/<path>
  ✓ Updated 3 pages (5 citations removed, 0 claims dropped)
  ✓ Rebuilt 1 evolving view
  ⚠ 1 shareable view left as-is (see below)
  ✓ Linter clean
```

## Unattended mode

`/forget` is **not available unattended**. The cascade involves
irreversible deletions and per-claim decisions that need the user in
the loop. If invoked unattended, refuse with a clear message and
suggest running it interactively.

## Rules

- Stop and ask before deleting any prose.
- Never delete a `shareable: true` view silently.
- Stay under 15 files per pass. Split across sessions if needed.
- If you can't find the source, ask for clarification — don't guess.
