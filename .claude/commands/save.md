---
description: Save the current conversation to conversations/ for later reference. These files feed /reflect when analyzing trajectory.
---

# /save — Save conversation

Save the current conversation as a markdown file in `conversations/`.
These files feed `/reflect` when it analyzes recent activity.

## When to use

- The session covered substantial vault territory.
- The session produced a useful synthesis.
- The user asks to save.

Don't save boilerplate exchanges.

## Behavior

1. Identify the topic (1-3 keywords).
2. Generate slug: `YYYY-MM-DD-<topic-slug>`.
3. If `/save <n>` was used, use that as slug.
4. Write to `conversations/<slug>.md`.
5. Append `## [YYYY-MM-DD] save | <slug>` to `wiki/log.md`.
6. Update `wiki/hot.md` with where we ended.
7. Confirm: "Saved to conversations/<slug>.md".

## Template

```markdown
---
date: YYYY-MM-DD
tags: [tag1, tag2]
pages_read:
  - [[wiki/pages/x]]
pages_written:
  - [[wiki/pages/x]]
views_used:
  - [[wiki/views/timeline-y]]
---

## Question
What the user asked.

## Answer
The synthesis or discussion, concise.

## Open
Threads left hanging, TODOs.
```

## Rules

- Distill. Don't dump the whole transcript.
- Don't invent links the session didn't use.
- Don't modify `wiki/pages/` as part of `/save` — that's a separate act.
- Do update `wiki/hot.md`.
