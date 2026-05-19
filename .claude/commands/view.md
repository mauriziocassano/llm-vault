---
description: Build a view — alternative representation of vault content. Kinds - timeline, comparison, concept-map, chart, slides, report, post. Writes to wiki/views/. Default shareable:false (evolves); shareable:true for slides/report/post if for external audience (frozen).
---

# /view [kind] [topic] — Build a view

Generate a view: an alternative representation of vault content.
Can be for the user's own understanding (default) or for sharing
externally. See `.claude/skills/view-builder/SKILL.md` for details.

## Kinds

- `timeline` — chronological ordering
- `comparison` — side-by-side table
- `concept-map` — Mermaid diagram
- `chart` — matplotlib PNG
- `slides` — Marp deck
- `report` — structured markdown
- `post` — blog-post-shaped markdown

## Behavior

1. Validate the kind and the topic(s) to feed the view.
2. If the kind is `slides`, `report`, or `post`, ask:
   > "Is this for you or to share with someone?"
   If external: `shareable: true`.
   Otherwise default: `shareable: false`.
3. For `timeline`, `comparison`, `concept-map`, `chart`: default
   `shareable: false` without asking.
4. Check if a view of the same kind on the same topic already exists.
   If `shareable: false`, propose updating it in place.
   If `shareable: true`, suggest creating a new dated file.
5. Load the matching template from
   `.claude/skills/view-builder/templates/view-<kind>.md`.
6. Fill it with real content, citing `[[wiki/...]]` for every claim.
7. For `chart`, copy `chart.py` too, adapt data, run it, save PNG
   to `wiki/views/assets/`.
8. Write to `wiki/views/<name>.md` (or `.html` for reveal).
9. Update `wiki/index.md` and append to `wiki/log.md`.
10. Tell the user the exact path.

## Naming

- Default: `<kind>-<topic>.md`
- If `shareable: true`: `YYYY-MM-DD-<slug>.<ext>` for clarity

## Rules

- `based_on` is mandatory.
- Every claim cites `[[wiki/...]]`.
- No invented data — if numbers aren't in the wiki, ask or abort.
- Propose outline first for complex kinds (reveal, multi-section reports).

## Example

User: `/view timeline agent-skills`

Agent reads `wiki/pages/agent-skills.md` and linked sources, writes
`wiki/views/timeline-agent-skills.md` with dated entries each citing
a source, updates index.md, replies:

> Wrote `wiki/views/timeline-agent-skills.md` — 14 entries across
> 2022-2026. Review in Obsidian.

User: `/view slides agent-skills`

Agent asks: "Is this for you or to share with someone?"

User: "For my team Monday, 20 min."

Agent proposes 8-slide outline, user confirms, agent writes
`wiki/views/2026-04-20-agent-skills-team-talk.md` with
`shareable: true`, replies:

> Draft at `wiki/views/2026-04-20-agent-skills-team-talk.md`.
> Marked shareable (frozen). Export with `marp <file> --pdf`.
