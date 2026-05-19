---
description: Reflect on the vault. Produces wiki/compass.md with three sections in prose - where my thinking is going, what I'm not looking at, and a question worth sitting with. Rewritten each time. Replaces the older dream-phase approach.
---

# /reflect — Write compass.md

Look at the last ~14 days of vault activity (conversations, views
touched, pages updated) and produce a single prose document at
`wiki/compass.md` with three sections. Rewrite from scratch each time.

## The output: three sections, all prose

### 1. Where my thinking is going

3-5 lines. Tell the user, in prose, what direction the window's
activity shows. Name concrete pages. Example:

> Over the last two weeks your attention has centered on agent
> skills and context engineering, touched most often together. You
> asked about skill composition eight times and about retrieval
> patterns five times, often in the same sessions. The direction
> looks like composable agent architectures.

### 2. What I'm not looking at

3-5 bullets. Concrete, with wiki links. Include, when relevant:

- **Adjacent pages not visited** — pages 1-2 hops from your hot
  clusters that never came up.
- **Unresolved tensions** — `#contradiction` markers in the wiki
  that no conversation touched.
- **Pages without structure** — hot topics with no views
  (timeline, comparison) that might help you see the shape.
- **Conversations with unincorporated insights** — recent saved
  conversations containing syntheses not yet in any page.
- **Views that could feed pages** — views cited repeatedly in
  conversations as if they were sources, not yet used to expand
  the underlying pages.
- **Structural issues** — duplicates, orphans, stale views
  (worth mentioning inline in prose, not in a separate list).

Each bullet is one-two sentences with a concrete link. No tables,
no sub-sections, no category labels in bold. Just bullets.

### 3. A question worth sitting with

One question. Embedded in a sentence of prose, not tagged or
labeled. Specific, uncomfortable, points at an absence. Examples:

> Given how much time you've spent reading about skill composition,
> why haven't you written anything down about how the two posts from
> Anthropic and Google actually disagree?

> You've understood this topic well enough to build three different
> views on it. What's stopping you from turning one of them into a
> post?

No "Hamming question" label. Just a question in the flow.

## Rules

- Prose, not structure. The user will read this once and act on it.
  A structured dashboard with five sections gets skipped.
- Specificity beats coverage. Two concrete observations beat six
  vague ones.
- Every claim about the user's activity cites concrete pages.
- No separate `candidates.md`. Structural suggestions go inline in
  section 2 when relevant.
- If the window is empty (few conversations, little activity), say
  so and keep the file short. Don't invent signal.

## Unattended mode

`/reflect` runs fine unattended. Write `compass.md`, update `log.md`
with `## [YYYY-MM-DD] reflect`. Do not modify any other file.

## How to identify signals

- **Hot pages:** count mentions across conversations in window,
  rank by frequency.
- **Adjacent pages:** pages linked from hot ones but not touched.
- **Unincorporated insights:** conversations from last 30 days where
  the user stated something the relevant page doesn't say.
- **Views cited as sources:** scan conversations for references like
  "in my timeline view" or "based on the comparison view"; if that
  view isn't in `based_on` of the underlying page, note it.

Keep these computations rough — they're heuristics for the prose,
not measurements for a dashboard.
