---
name: vault-linter
description: Runs deterministic health checks on a second brain wiki vault (dead links, orphan pages, duplicates, missing metadata, inconsistent naming, stale sources, gaps, view staleness, missing cross-references) and writes a report to .lint/report.md. Use this skill when the user says "lint", "check the vault", "vault health", "find broken links". Also run periodically — triggered when 5+ ingests have occurred since last lint OR 7+ days have passed. Supports unattended mode via --unattended flag. Fast, no LLM tokens consumed.
---

# Vault Linter

Deterministic health check for the vault. Runs in milliseconds, uses
zero LLM tokens.

## When to use

- The user says "lint", "check the vault", "find broken links".
- Before `/reflect`, if `.lint/state.yaml` shows staleness (≥5 ingests
  or ≥7 days since last lint).
- After a batch of ingests, to verify integrity.
- Unattended mode, scheduled.

## What it checks

Nine deterministic checks. Each produces findings with concrete paths.

| # | Check | What it catches |
|---|---|---|
| 1 | **Dead links** | `[[path]]` pointing to non-existent files |
| 2 | **Orphan pages** | Pages with zero incoming links (excluding hot.md, compass.md, index.md, views) |
| 3 | **Duplicate concepts** | Pages with similar titles within the same subdir |
| 4 | **Missing metadata** | Frontmatter missing required fields for the type |
| 5 | **Inconsistent naming** | Same concept referenced by different names |
| 6 | **Stale sources** | `wiki/sources/` pages not updated in >180 days |
| 7 | **Gaps** | Concept names in prose without a corresponding page |
| 8 | **View staleness** | Evolving views (`shareable: false`) whose `based_on` pages changed more than 30 days after |
| 9 | **Missing cross-references** | Source pages citing a page in prose without a link |

Checks 3, 5, 7, 9 are heuristic — they can produce false positives and
are marked as advisory.

## How to run

```bash
# From vault root
python .claude/skills/vault-linter/scripts/lint.py

# Unattended (no prompts)
python .claude/skills/vault-linter/scripts/lint.py --unattended

# From outside the vault
python .claude/skills/vault-linter/scripts/lint.py --vault /path/to/vault
```

## Exit codes

- `0` — clean (no findings)
- `1` — findings present (expected; not a failure)
- `2` — script error

## Output

### `.lint/report.md`

Findings grouped by severity:

- **Blocking** — dead links, missing required metadata.
- **Important** — orphans, gaps.
- **Advisory** — duplicates, stale, naming, view staleness.

### `.lint/state.yaml`

```yaml
last_lint: 2026-04-18
ingests_since_last_lint: 0
last_exit_code: 1
last_findings_count: 12
```

## Dependencies

Python standard library only. No pip install needed.

## What the linter does NOT do

- **Does not fix anything.** Reports only.
- **Does not use an LLM.** Pure Python on text and filesystem.
- **Does not validate semantic content.** That's for `/reflect`.

## How the agent uses the output

**Interactive:** read report, summarize ("X blocking, Y important,
Z advisory"), offer to fix blocking issues now.

**Unattended:** run, if catastrophic (>50 dead links) abort any
subsequent `/reflect`. Otherwise note lint summary in `compass.md`
as a brief footer.

## Heuristic checks — expected false positive rates

- **Duplicate concepts:** ~10-20%
- **Inconsistent naming:** ~15%
- **Gaps:** ~30%
- **Missing cross-references:** ~20%

Tagged `[advisory]` in the report. The user decides what to act on.
