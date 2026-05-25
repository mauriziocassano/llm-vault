# Second Brain Vault

A self-maintaining personal knowledge vault pattern, inspired by
[Andrej Karpathy's LLM Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

You curate sources. The agent compiles a wiki, answers your
questions, builds views when you ask, and periodically reflects on
where your thinking is going. Works with Claude Code, Codex, or any
agent that reads `CLAUDE.md` or `AGENTS.md`.

**→ Read [GETTING-STARTED.md](GETTING-STARTED.md) first.**

---

## Origin and attribution

This project is a fork of [maeste/my-2nd-brain](https://github.com/maeste/my-2nd-brain),
itself inspired by [Andrej Karpathy's LLM Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

See [What's changed from the original](#whats-changed-from-the-original) for a summary
of modifications made in this fork.

---

## What's in this project

```
├── init-vault.sh         bootstrap script (run first)
├── CLAUDE.md             the contract between you and the agent (~230 lines)
├── AGENTS.md             symlink to CLAUDE.md for Codex / OpenAI agents
├── GETTING-STARTED.md    10-minute walkthrough for newcomers
├── README.md             this file
├── skills/
│   ├── inbox-fetcher/         two-phase: Playwright + agent vision → raw/
│   ├── inbox-fetcher-legacy/  original trafilatura-only fetcher (fallback)
│   ├── vault-linter/          9 deterministic health checks
│   └── view-builder/          timelines, comparisons, charts, slides, reports, posts
├── commands/
│   ├── save.md           /save
│   ├── view.md           /view
│   ├── reflect.md        /reflect
│   └── forget.md         /forget
└── docs/examples/
    ├── research-example.md
    └── mealplan-example.md
```

---


## Quick start

```bash
git clone https://github.com/mauriziocassano/llm-vault.git
cd llm-vault
./init-vault.sh                    # → ./second-brain-vault
# or
./init-vault.sh ~/knowledge/X      # explicit path
# or
./init-vault.sh --here             # current directory
```

Script is idempotent — safe to re-run.

Then open Claude Code (or another CLI) in the vault and follow
[GETTING-STARTED.md](GETTING-STARTED.md).

### Updating an existing vault

Re-running `init-vault.sh` against an existing vault is the update
path. After `git pull` in this repo, re-run the script pointing at
your vault:

```bash
./init-vault.sh ~/knowledge/X   # or --here, or default path
```

What happens on re-run:

- **Always refreshed** — `skills/` and `commands/`. This is the
  whole point of the update: new operations, fixes, and slash
  commands land in the vault.
- **Prompts you** — `CLAUDE.md`. Default is *keep* (answer `y` to
  overwrite with the latest template). Say yes unless you've
  customized the contract locally.
- **Created only if missing** — `inbox.md`, `wiki/index.md`,
  `wiki/log.md`, `wiki/threads.md`, `.lint/state.yaml`, `.gitignore`.
- **Never touched** — `raw/`, `wiki/pages/`, `wiki/sources/`,
  `wiki/views/`, `conversations/`, `wiki/compass.md`. Your
  knowledge and ongoing work are safe.

No separate `update-vault.sh` exists because `init-vault.sh` already
does the right thing.

---

## The core idea, in one paragraph

A directory `raw/` with immutable sources. An agent that compiles
them into a wiki of markdown pages. Queries against that wiki,
answered by the agent with citations. Views (timelines, comparisons,
slides) built on demand. A periodic `/reflect` that writes prose
about where your thinking is going. All of it evolves together — ask
Karpathy calls it *compounding*: every source you add, every
conversation you save, every view you build, increases what the next
question can draw on.

---

## Design principles

Six invariants:

1. **Raw is immutable.** If the wiki is corrupted, it's recompilable
   from `raw/` alone.
2. **Every claim cites a source.** No orphan claims in the wiki.
3. **Paraphrase, don't copy.** Summaries are in the agent's words.
4. **You curate, the agent maintains.** No auto-fetching, no
   auto-structural changes, no views without your request.
5. **`shareable: true` views are frozen.** Anything else evolves.

---

## Dependencies

**For `inbox-fetcher`** (Python + Playwright):

```bash
pip install trafilatura requests python-slugify beautifulsoup4 lxml markdownify playwright
python3 -m playwright install chromium
```

For YouTube transcripts (optional):

```bash
brew install yt-dlp    # macOS
```

**For `vault-linter`** and **`view-builder`**:
Python standard library only. For charts (optional):

```bash
pip install matplotlib
```

**For the agent**: Claude Code, Codex, or any CLI that reads
`CLAUDE.md` / `AGENTS.md` and supports slash commands.

---

## Troubleshooting

**`python3: command not found`** → install Python 3.10+.

**Inbox fetcher fails on some URLs** → likely a JS-rendered page, a
paywall, or a walled domain (X/Twitter, LinkedIn, Threads, Facebook,
Instagram). The fetcher already makes one headless Playwright attempt
automatically. If that is blocked (login wall), it marks the URL
`⚠ blocked — chrome-devtools-mcp` and leaves it unchecked. The agent
then runs an interactive Chrome DevTools MCP pass for each blocked URL
(one confirmation per URL), using your real browser session. See the
*Chrome DevTools MCP protocol* section in `skills/inbox-fetcher/SKILL.md`.
Obsidian Web Clipper remains a manual fallback if Chrome DevTools MCP
is unavailable.

**I have local files I want to add** → drop `.md` or `.pdf` files in
`.tmp/` at the vault root, then ask "process the inbox".
`.md` files land in `raw/docs/<slug>/` with vault-standard frontmatter.
`.pdf` files land in `raw/papers/<slug>.pdf` as a direct copy.
Originals are deleted from `.tmp/` after processing.

**Linter flags many orphan pages early on** → expected. Orphan check
becomes meaningful when the wiki has >50 pages. Views are
automatically exempt.

**`/reflect` has little to say** → probably not enough saved
conversations. Use `/save` more. Also needs a few weeks of activity
before the signals land.

**AGENTS.md not recognized** → replace the symlink with a copy:
`rm AGENTS.md && cp CLAUDE.md AGENTS.md`.

---

## What's changed from the original

Key additions and changes made in this fork relative to [maeste/my-2nd-brain](https://github.com/maeste/my-2nd-brain):

- **Two-phase inbox fetcher** — replaced the original trafilatura-only fetcher with a
  two-phase architecture: Python script (Playwright + trafilatura, image triage, chart
  extraction) followed by an agent vision pass. Original preserved as `inbox-fetcher-legacy/`.
- **Local file ingestion via `.tmp/`** — drop `.md` or `.pdf` files into `.tmp/`,
  say "process the inbox". Files land in `raw/docs/` or `raw/papers/` with vault-standard
  frontmatter. Originals deleted from `.tmp/` after processing.
- **Replaced `hot.md` with `threads.md`** — persistent open-thread tracker that survives
  session boundaries. Threads close via a three-step protocol (save conversation →
  append to log.md → remove thread) leaving a full audit trail. `compass.md` is now
  read at every QUERY for vault-direction context.
- **Session-start protocol** — CLAUDE.md explicitly mandates reading `memory/MEMORY.md`
  then `wiki/threads.md` at every session start, in that order.
- **Memory folder in vault** — project-specific memory (user profile, naming conventions,
  feedback, commit workflow) lives in `memory/` inside the vault, gitignored and
  local to the user.
- **Vault content gitignored** — `raw/`, `wiki/`, `conversations/`, `memory/`, `inbox.md`
  excluded from git so only the system source code (skills, commands, CLAUDE.md) is pushed.

---

## Evolving the contract

`CLAUDE.md` is designed to co-evolve. When you hit friction, ask the
agent to propose a change. Good changes get committed; bad ones get
reverted. Your vault, your rules.

---

## License and attribution

MIT — see [LICENSE](LICENSE).

Built on the pattern described by [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
Forked from [maeste/my-2nd-brain](https://github.com/maeste/my-2nd-brain).
