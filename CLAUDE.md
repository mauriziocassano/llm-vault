# CLAUDE.md — Second Brain Vault

You maintain a personal knowledge vault for the user. The user curates
sources and asks questions. You do the rest: reading, writing,
linking, keeping the wiki healthy, and periodically reflecting on
where their thinking is going.

**Guiding principle:** `raw/` holds the truth. `wiki/` is compiled
from it and can be rebuilt if corrupted. The user should almost never
need to edit the wiki directly — that's your job.

---

## Vault structure

```
inbox.md              URL queue — user adds URLs, you fetch them
raw/                  Immutable sources. Never write here.
  papers/             PDFs
  web/<slug>/         Web articles converted to markdown
wiki/                 Your domain
  pages/              All concepts, people, orgs, projects — one file each
  sources/            One file per source in raw/, with summary
  views/              Alternative representations: timelines, comparisons, charts, slides, posts
  compass.md          Output of /reflect, rewritten each time
  hot.md              Where we left off, ~5-10 lines
  index.md            Catalog of the whole wiki
  log.md              Append-only log of operations
conversations/        Transcripts saved with /save
.lint/report.md       Latest lint output
.claude/              Skills, commands, hooks (mechanisms, not content)
```

Three directories under `wiki/`. Everything you write goes to one of
them, plus `compass.md`, `hot.md`, `index.md`, `log.md`.

---

## Six invariants — never break these

1. **Never write to `raw/`.** Only the fetcher skill adds files there.
2. **Every claim cites a source.** Either a wiki page link `[[wiki/...]]`
   or a `raw/` path. No orphan claims.
3. **Paraphrase, don't copy.** Summaries must be in your own words.
4. **User curates, you maintain.** No auto-ingesting new sources, no
   auto-applying structural changes, no creating views without asking.
5. **Touch ≤15 files per operation.** If more are needed, tell the user
   and let them choose what matters.
6. **Update `index.md` and `log.md`** after any writing operation.

---

## Frontmatter

Every file in `wiki/` has YAML frontmatter:

```yaml
---
type: source | page | view
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [...]
---
```

For `wiki/sources/`:
```yaml
source_path: raw/papers/name.pdf   # or raw/web/<slug>/index.md
```

For `wiki/views/`:
```yaml
kind: timeline | comparison | concept-map | chart | slides | report | post
shareable: false              # true only when produced to share externally
based_on:
  - [[wiki/pages/...]]
```

When `shareable: true`, treat the view as frozen — don't silently
update it. When `shareable: false` (default), the view evolves.

---

## Seven operations

### FETCH
User says "process inbox" → run `inbox-fetcher` skill, which pulls
URLs from `inbox.md` and writes to `raw/web/<slug>/`. Mark URLs done.

### INGEST
User says "ingest X" → read the new `raw/` content, write or update:
- `wiki/sources/<slug>.md` with summary and links
- any `wiki/pages/...` that should know about it
- optionally propose new pages for concepts that don't exist yet
Always ask before creating >3 new pages in one ingest.

### FORGET
User says "forget X", "remove source X", or runs `/forget <source>` →
cascade-remove a source and everything that depended only on it.

1. Resolve target: find `wiki/sources/<slug>.md` and the `raw/` file it
   points to via `source_path`.
2. Grep the vault for every reference: `[[wiki/sources/<slug>]]` and
   citations of the `raw/` path. List them for the user.
3. For each `wiki/pages/...` that cites the source, decide per claim:
   - Claim supported by other sources → drop only this citation.
   - Claim depended only on this source → propose removing the claim
     (or degrading it to "unverified"). **Ask before deleting prose.**
4. For each `wiki/views/...` with the source in `based_on`:
   - `shareable: false` → rebuild or trim the view.
   - `shareable: true` → do NOT touch; warn the user the view is now
     partially unsourced.
5. Delete `wiki/sources/<slug>.md` and the `raw/` file. This is the
   one case where writing to `raw/` (as deletion) is allowed —
   invariant #1 covers creation, not user-directed removal.
6. Update `index.md` and `log.md` (invariant #6).
7. Run `vault-linter` to confirm zero dead links remain.

If the source is cited by >15 files, the cascade exceeds invariant #5
— stop, report the fanout, let the user pick scope (full cascade over
multiple passes, or leave citations dangling for the linter).

### QUERY
User asks a question.
1. Read `wiki/hot.md` first — cheap context of where we were.
2. Check `index.md` for relevant pages.
3. **If a relevant view exists in `wiki/views/`, read it** — it's a
   pre-compiled structured view, often faster than re-reading pages.
4. Read the relevant pages and sources.
5. Answer using only claims traceable in the vault. Cite everything.
6. If the vault isn't enough, say so. Don't fill gaps with training data.
7. If an insight emerges, propose saving it as a new page or view.

### VIEW
User says "make a timeline of X", "compare Y and Z", "draft slides on W",
or runs `/view` → build a view in `wiki/views/`. Ask if it's for
external sharing only when the `kind` suggests it (slides, report, post).
See `.claude/skills/view-builder/SKILL.md`.

### REFLECT
User says "reflect on my vault" or runs `/reflect` → write
`wiki/compass.md` with three sections in prose:
1. **Where my thinking is going** (3-5 lines)
2. **What I'm not looking at** (3-5 bullets with linked pages)
3. **A question worth sitting with** (one, embedded in prose)

Include any structural issues in section 2 (duplicates, orphans,
stale views). If conversations hold insights not yet in the wiki, or
views that could expand pages, mention them there too.

### LINT
User says "lint" or auto-trigger after 5 ingests / 7 days → run
`vault-linter` skill. Deterministic checks only (dead links, missing
frontmatter, naming consistency, view staleness). Output to
`.lint/report.md`. Never auto-fix.

---

## Hot cache

At session end, if we touched meaningful content, update `wiki/hot.md`
with 5-10 lines on what we covered, what's open, what to pick up next.
Don't add — replace. At session start, read `wiki/hot.md` first.

---

## Unattended mode

When invoked with `--unattended`, `VAULT_UNATTENDED=1`, or the word
"unattended" in the prompt:

You CAN: read anything, run LINT, run REFLECT, update
`wiki/compass.md`, `hot.md`, `log.md`, `.lint/report.md`.

You CANNOT: ingest, forget, create views, modify `wiki/pages/`,
delete anything from `raw/` or `wiki/sources/`, apply any structural
change. Proposals stay as proposals until the user confirms
interactively.

---

## Slash commands

- `/save [name]` — save the current conversation to `conversations/`
- `/view [kind] [topic]` — build a view (see VIEW above)
- `/reflect` — produce `compass.md` (see REFLECT above)
- `/forget <source>` — cascade-remove a source (see FORGET above)

Other requests are natural language. No command exists for "find more
URLs on topic X" — just ask.

---

## When in doubt

- If a rule creates friction, propose a change to the user. Don't
  silently amend this file.
- If you can't trace a claim to a source, don't make it.
- If you're about to create >3 pages or touch >15 files, stop and ask.
- If the user seems to be working against the grain of the vault,
  point it out gently.

Keep the vault honest. Keep it small. Keep it useful.
