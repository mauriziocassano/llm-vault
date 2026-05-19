# Example: research vault on agent skills

A worked example showing the pattern in a canonical technical domain.

---

## Setup

You're doing research on LLM agent skills — their design, their
limits, how they compose. You want to track this over months, build
a coherent picture, eventually give a talk about it.

```bash
./init-vault.sh ~/research/agent-skills
cd ~/research/agent-skills
```

---

## Day 1: first batch of sources

You add 6 URLs to `inbox.md`:

```markdown
## To process
- [ ] https://www.anthropic.com/engineering/agent-skills
- [ ] https://simonwillison.net/2024/12/agent-patterns/
- [ ] https://research.google/pubs/agent-tool-composition/
- [ ] https://arxiv.org/abs/2024.09876
- [ ] https://openai.com/blog/function-calling-update
- [ ] https://langchain.com/blog/skill-libraries
```

Open Claude Code. *"Process the inbox."*

The agent runs `inbox-fetcher`, pulls the 6 pages into
`raw/web/*/index.md`, moves them to `## Done` in `inbox.md`.

*"Now ingest the new content."*

Agent reads each file, proposes the structure:

> I'll create 6 source summaries and 5 pages:
> `agent-skills`, `function-calling`, `tool-composition`,
> `skill-composition`, `anthropic` (org). OK?

You say yes. Agent writes:

```
wiki/sources/
  anthropic-agent-skills.md
  simonwillison-agent-patterns.md
  google-agent-tool-composition.md
  arxiv-2024-09876.md
  openai-function-calling-update.md
  langchain-skill-libraries.md
wiki/pages/
  agent-skills.md
  function-calling.md
  tool-composition.md
  skill-composition.md
  anthropic.md
```

Each source cites its `raw/` path and summarizes. Each page cites
the sources that mention it.

---

## Day 4: questions

*"What are the main disagreements between the Anthropic and Google
takes on skill composition?"*

Agent reads `wiki/pages/skill-composition.md`, the two relevant
sources, responds with a structured answer and explicit citations.

*"Actually save this conversation."* → `/save agent-skills-tension`

Saved to `conversations/2026-04-22-agent-skills-tension.md`.

---

## Week 2: first view

*"I want to see how thinking on this has evolved. Build me a
timeline."* → `/view timeline agent-skills`

Agent reads all relevant pages and sources, writes
`wiki/views/timeline-agent-skills.md`:

- 2023: initial function-calling paradigm
- 2024-Q1: first attempts at composition
- 2024-Q3: divergence between Anthropic and Google
- 2024-Q4: spec consolidation
- 2026: current state

Each entry cites its source. `shareable: false` by default (this is
for you).

Now when you ask *"when did the consolidation happen?"*, the agent
reads the timeline view first — faster and more structured than
re-reading six sources.

---

## Week 3: reflection

You've saved 4 conversations. Run `/reflect`.

Agent writes `wiki/compass.md`:

> **Where my thinking is going**
>
> In the last two weeks you've centered on [[wiki/pages/skill-composition]]
> (8 hits) and [[wiki/pages/tool-composition]] (5 hits), almost
> always together. The direction looks like composable agent
> architectures — you're less interested in single-skill design
> and more in how skills interact.
>
> **What I'm not looking at**
>
> - [[wiki/pages/function-calling]] has 4 incoming links from your
>   hot pages but you haven't visited it in three weeks. Worth a
>   revisit — it's the foundation.
> - Your timeline view [[wiki/views/timeline-agent-skills]] is cited
>   in two conversations but nothing in [[wiki/pages/agent-skills]]
>   references it. Might be worth expanding the page from what the
>   view knows.
> - The [[wiki/sources/openai-function-calling-update]] and
>   [[wiki/sources/arxiv-2024-09876]] disagree about whether skills
>   need explicit type declarations — you never resolved this.
>
> **A question worth sitting with**
>
> You've read fifteen sources and built a timeline. What's stopping
> you from writing down, in your own words, what you actually think
> skill composition should look like?

You read this, spend 30 minutes writing a page
`wiki/pages/my-take-on-skill-composition.md`, and feel the vault has
started paying you back.

---

## Week 6: an artifact

You're giving a team talk. *"Make slides on agent skills, for my
engineering team, 20 minutes."* → `/view slides agent-skills`

Agent asks about `shareable` (yes, external), proposes an 8-slide
outline based on the pages and the timeline view, you tweak, agent
writes `wiki/views/2026-06-01-agent-skills-team-talk.md` with
`shareable: true` and citations.

You run `marp <file> --pdf`, give the talk. The file stays frozen.
If you give the talk again in October with updated material, that's
a new file `2026-10-15-...`, not an overwrite.

---

## What the pattern gives you

After three months on this vault:

- **Everything you've read is findable** — not in your memory, but
  in the wiki with citations and connections.
- **Views compress understanding** — the timeline and two
  comparison views have become your go-to when you need to think
  about this area.
- **`/reflect` is the killer feature** — not the content of the
  compass itself, but the discipline of having something look at
  your thinking and ask hard questions.
- **You still curate** — no auto-fetching, no auto-ingestion, no
  structural changes without asking. The vault stays yours.
