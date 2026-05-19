# Second Brain Vault 

A self-maintaining personal knowledge vault pattern, based on
[Andrej Karpathy's LLM Wiki idea](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

You curate sources. The agent compiles a wiki, answers your
questions, builds views when you ask, and periodically reflects on
where your thinking is going. Works with Claude Code, Codex, or any
agent that reads `CLAUDE.md` or `AGENTS.md`.

**→ Read [GETTING-STARTED.md](GETTING-STARTED.md) first.**

---

## What's in this project

```
vault-bundle/
├── init-vault.sh         bootstrap script (run first)
├── CLAUDE.md             the contract between you and the agent (~175 lines)
├── GETTING-STARTED.md    10-minute walkthrough for newcomers
├── README.md             this file
├── skills/
│   ├── inbox-fetcher/    URL → markdown in raw/
│   ├── vault-linter/     9 deterministic health checks
│   └── view-builder/     timelines, comparisons, charts, slides, reports, posts
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
git clone https://github.com/maeste/my-2nd-brain.git
cd my-2nd-brain
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
  `wiki/log.md`, `wiki/hot.md`, `.lint/state.yaml`, `.gitignore`.
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

Five invariants:

1. **Raw is immutable.** If the wiki is corrupted, it's recompilable
   from `raw/` alone.
2. **Every claim cites a source.** No orphan claims in the wiki.
3. **Paraphrase, don't copy.** Summaries are in the agent's words.
4. **You curate, the agent maintains.** No auto-fetching, no
   auto-structural changes, no views without your request.
5. **`shareable: true` views are frozen.** Anything else evolves.

---

## Dependencies

**For `inbox-fetcher`** (Python):

```bash
pip install trafilatura requests python-slugify
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

**`python: command not found`** → install Python 3.10+.

**Inbox fetcher fails on some URLs** → likely paywall, JS-rendered, or
a walled domain (X/Twitter, LinkedIn, Threads, Facebook, Instagram).
The fetcher marks these `⚠ ... — try playwright` and leaves them
unchecked. The agent can then fetch them interactively via the
Playwright MCP (one URL at a time, with your confirmation). See the
*Playwright fallback* section in `skills/inbox-fetcher/SKILL.md`.
Obsidian Web Clipper remains a manual fallback if Playwright MCP is
unavailable.

**Linter flags many orphan pages early on** → expected. Orphan check
becomes meaningful when the wiki has >50 pages. Views are
automatically exempt.

**`/reflect` has little to say** → probably not enough saved
conversations. Use `/save` more. Also needs a few weeks of activity
before the signals land.

**AGENTS.md not recognized** → replace the symlink with a copy:
`rm AGENTS.md && cp CLAUDE.md AGENTS.md`.

---

## Evolving the contract

`CLAUDE.md` is designed to co-evolve. When you hit friction, ask the
agent to propose a change. Good changes get committed; bad ones get
reverted. Your vault, your rules.

---

## License and attribution

MIT. Built on the pattern described by
[Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
