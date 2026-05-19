---
name: view-builder
description: Build views from vault content. A view is an alternative representation: timeline, comparison, concept map, chart, slides, report, or post. Use whenever the user says "make a timeline", "compare X and Y", "draft slides", "chart the sources", "/view", or asks for any elaborated output grounded in the wiki. Writes to wiki/views/ with frontmatter that includes provenance (based_on). Views with shareable:false evolve in place; shareable:true views are treated as frozen snapshots.
---

# View Builder

A view is an alternative representation of vault content. It can be
for the user's own understanding (the default) or for sharing
externally. One concept, one folder, one slash command.

## When to use

Natural triggers:
- "make a timeline of X"
- "compare X and Y"
- "draft slides on Z"
- "chart the sources by year"
- "concept map of W"
- "write a report/post on V"
- `/view [kind] [topic]`

## The seven kinds

| Kind | What it is | Template |
|---|---|---|
| timeline | Chronological ordering | `view-timeline.md` |
| comparison | Side-by-side table of 2-4 things | `view-comparison.md` |
| concept-map | Mermaid diagram + notes | `view-concept-map.md` |
| chart | Matplotlib-generated PNG + caption | `view-chart.md` + `chart.py` |
| slides | Marp slide deck | `view-slides.md` |
| report | Structured markdown report | `view-report.md` |
| post | Blog-post-shaped markdown | `view-post.md` |

## Shareable or not

**Default: `shareable: false`** — the view is for the user. It evolves.
The agent reads it during QUERY as a pre-compiled structured view.

**Ask about shareable only when the kind implies external audience.**
- For `timeline`, `comparison`, `concept-map`, `chart`: default to
  `shareable: false` and don't ask.
- For `slides`, `report`, `post`: ask "is this for you or to share
  with someone?"

When `shareable: true`, treat it as a snapshot. Don't modify silently.
If the user asks to update later, confirm explicitly: "this is marked
shareable — you want to edit in place or create a new dated file?"

## Workflow

1. Confirm the kind if ambiguous.
2. Identify the pages that feed the view (`based_on`).
3. For `slides`/`report`/`post` ask about `shareable` and the audience.
4. For complex kinds (reveal decks, multi-page reports), propose the
   outline before writing the full file.
5. Load the right template.
6. Fill it with real content, citing `[[wiki/...]]` for every claim.
7. For `chart`, also run `chart.py` to produce the PNG in
   `wiki/views/assets/`.
8. Write to `wiki/views/<slug>.md` (or `.html` for reveal).
9. Update `wiki/index.md` (add to a "Views" section).
10. Append to `wiki/log.md`: `## [YYYY-MM-DD] view | <slug>`.
11. Tell the user the exact path.

## Naming

Default: `<kind>-<topic>.md`. Example: `timeline-agent-skills.md`,
`comparison-tofu-tempeh.md`.

If `shareable: true`, optionally date-prefix for clarity:
`2026-04-20-agent-skills-team-talk.md`.

If a second view of the same kind on the same topic is needed,
disambiguate: `timeline-agent-skills-enterprise.md`.

## Frontmatter

```yaml
---
type: view
kind: timeline | comparison | concept-map | chart | slides | report | post
created: YYYY-MM-DD
updated: YYYY-MM-DD
shareable: false           # true only if explicitly for external use
based_on:
  - [[wiki/pages/...]]
  - [[wiki/sources/...]]
purpose: "One-sentence description of what this view helps see."
---
```

`based_on` is **mandatory**. The linter uses it. REFLECT uses it.

## Rules

- **Cite everything.** Every claim must trace to `based_on` entries.
- **Don't invent data.** For charts, if numbers aren't in the wiki,
  ask the user to supply them or abort.
- **Paraphrase, don't transcribe.** Views are synthesis.
- **Confirm before writing** when the view is large (slides with >8
  slides, reports with >5 sections).
- **Update in place** for `shareable: false`. Bump `updated`.
- **Don't modify** `shareable: true` views without explicit ok.

## What this skill doesn't do

- Render PDF/HTML from Marp or Reveal — the user does that separately.
- Auto-generate views — producing is always a deliberate act.
- Read `shareable: true` views during future QUERY unless asked.
