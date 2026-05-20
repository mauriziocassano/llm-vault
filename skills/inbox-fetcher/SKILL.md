---
name: inbox-fetcher-vision
description: Two-phase vision-enhanced inbox fetcher for a second brain vault. Phase 1 (Python script): HTML + PDF + YouTube + walled-domain fetching with conditional headless Playwright for JS pages, image triage by rendered bounding box (sorted by area, capped at 15), chart extraction (inline JS config + canvas screenshot), and figure screenshots to assets/__pending/. Phase 2 (agent): vision-transcribes each figure into > [DIAGRAM:] / > [CHART:] blocks and runs an interactive Chrome DevTools MCP pass for login-walled URLs. Use this skill when the user mentions "inbox", "fetch", "process links", "scrape URLs", or "download articles" — prefer over inbox-fetcher when images, diagrams, or charts in the source content matter. Handles local .md files from .tmp/ and URLs from inbox.md. Supports PDF, YouTube transcripts (yt-dlp), and arxiv rewrites.
---

# Inbox Fetcher Vision

Processes two input channels into clean files under `raw/`, ready for INGEST:

1. **URLs** from `inbox.md` → `raw/web/` (HTML/YouTube) or `raw/papers/` (PDF)
2. **Local `.md` files** from `.tmp/` → `raw/docs/`

Visual content (diagrams, charts, content images) is preserved as transcribed text
via a two-phase architecture: Phase 1 (Python script) captures the content mechanically;
Phase 2 (agent) interprets it visually.

## Architecture: two distinct browser engines

This skill uses **both** Playwright and Chrome DevTools MCP, for different stages:

| Component | Stage | Role | User interaction |
|---|---|---|---|
| **Playwright Python library** | Phase 1 (headless, automated) | Renders JS-heavy pages; screenshots content images and canvas charts | None |
| **Chrome DevTools MCP** | Phase 2 (interactive, agent-driven) | Fallback for login-walled URLs; hooks into user's real Chrome with existing sessions | Required per URL |

## Architecture: two-phase hybrid

```
Phase 1 — Python script (fetch_inbox.py)           [mechanical only]
  ├─ HTTP fetch (trafilatura or requests)
  ├─ Text track: trafilatura → Playwright fallback (if quality insufficient)
  ├─ Visual track: conditional — Playwright only when:
  │   ├─ text quality is insufficient, OR
  │   ├─ static HTML contains candidate content images, OR
  │   └─ static HTML contains chart library signatures or <canvas>
  │   ├─ Image triage: heuristic filter → bbox area gate → sort by area →
  │   │   cap at 15 → screenshot to assets/__pending/
  │   ├─ Chart Strategy 1: inline JS config (Chart.js/Plotly/Highcharts)
  │   └─ Chart Strategy 2: canvas screenshot (fallback)
  ├─ Auth-wall detection → blocked manifest
  └─ Emits: raw/web/<slug>/index.md (draft, with <!--FIG:N--> placeholders)
            raw/web/<slug>/.fetch-manifest.json
            raw/web/<slug>/assets/          (full-res originals)
            raw/web/<slug>/assets/__pending/  (element screenshots for vision)

Phase 2 — Agent orchestration                      [vision + Chrome DevTools MCP]
  ├─ Read each .fetch-manifest.json
  ├─ Per figure with screenshot: vision-transcribe → > [DIAGRAM: …] block
  ├─ Per chart with chart_config: render JSON as markdown table → > [CHART:] block
  ├─ Replace <!--FIG:N--> placeholders in index.md
  ├─ Blocked URLs: confirm with user → Chrome DevTools MCP interactive pass
  ├─ Delete assets/__pending/ (scaffolding; full-res originals in assets/ remain)
  ├─ Update index.md frontmatter (transcribed: true, figure_count)
  └─ Update inbox.md (mark done / move to ## Done)
```

The script **never** calls vision or MCP tools. The agent **never** re-fetches HTML.

## Vault assumptions

```
<vault>/
├── inbox.md              URL queue (checkbox format)
├── .tmp/                 drop local .md files here for processing
├── raw/
│   ├── web/              HTML article output
│   ├── papers/           direct PDF downloads
│   └── docs/             local .md file output
└── skills/
    └── inbox-fetcher-vision/
        ├── SKILL.md
        └── scripts/
            ├── fetch_inbox.py       Phase 1 script
            ├── extract_charts.py    chart JS extraction (callable, no /tmp)
            └── _strip.py            boilerplate strip constants + helpers
```

All `raw/` subdirectories are created on demand. `.tmp/` is optional — if absent, local processing is silently skipped.

## Inbox format

```markdown
# Inbox

## To process

- [ ] https://www.anthropic.com/engineering/agent-skills
- [ ] https://example.com/paper-x.pdf
  - tags: agent-skills, spec
  - note: focus on composition

## Done

- [x] https://old-url.com → `raw/web/old-url-slug/` (2026-04-15)
- [x] (local) my-notes.md → `raw/docs/my-notes/` (2026-05-20)
```

Rules:

- Only lines matching `- [ ] <URL>` (unchecked) are processed.
- Indented sub-bullets (tags, notes) are preserved but not parsed.
- After a successful fetch + agent vision pass, the line moves to `## Done`
  marked `- [x]` with output path and date.
- Failed fetches get an inline `⚠ <reason>` suffix and stay unchecked.
- Blocked (login wall) lines carry: `⚠ blocked (login wall) — chrome-devtools-mcp`.
- Legacy `## Processati` or `## Processed` sections are automatically renamed/merged
  into `## Done` on the next run.

## Phase 1: running the script

From the vault root:

```bash
python skills/inbox-fetcher-vision/scripts/fetch_inbox.py
```

Or from anywhere:

```bash
python skills/inbox-fetcher-vision/scripts/fetch_inbox.py --vault /path/to/vault
```

Use `--dry-run` to see what would be processed without fetching.

The script is idempotent: already-processed URLs (marked `[x]`) are skipped.
To re-fetch a URL, un-check it manually in `inbox.md`.

## Escalation ladder (per URL)

After the arxiv→PDF rewrite:

```
A. PDF (path ends .pdf OR Content-Type application/pdf)
     → fetch_pdf() → raw/papers/<slug>.pdf           [no agent phase needed]

B. YouTube URL (youtube.com, youtu.be, m.youtube.com, youtube-nocookie.com)
     → fetch_youtube_transcript() via yt-dlp
       success → raw/web/<slug>/index.md, fetch_method: yt-dlp-*
       no subtitles → ⚠ no subtitles available …

C. Walled host (X/Twitter, LinkedIn, Threads, Facebook, Instagram)
     → headless Playwright attempt first (auto).
       readable content → treat as D result.
       auth wall detected → blocked manifest.
                            inbox line: ⚠ blocked — chrome-devtools-mcp

D. Default HTML — Playwright is launched only if needed (see below):
   Need-Playwright triggers (any one is sufficient):
     - trafilatura returned < 200 words OR integrity_delta ≥ 30%
     - static HTML contains candidate content images (heuristic pre-filter)
     - static HTML contains chart library signatures or <canvas> elements

   Text track:
     trafilatura.fetch_url + extract.
       quality OK → text_source=trafilatura
       quality insufficient → Playwright render → text_source=playwright

   Visual track (only when need_playwright is True):
     Playwright DOM query for img elements → bbox area gate → sort by area →
     cap at 15 → screenshot survivors to assets/__pending/
     Chart Strategy 1: extract inline JS config
     Chart Strategy 2: canvas screenshot (when no JS config extracted)
```

`domcontentloaded` wait is used; `networkidle` is **forbidden** (times out on
analytics-heavy pages in production).

## Image triage

An image is dropped if **any** of:

- `src` is `data:image` (inline blob)
- Basename matches DECORATIVE_NAMES: `logo`, `icon`, `avatar`, `spinner`, `pixel`,
  `tracker`, `analytics`, `1x1`, `arrow`, `close`, `menu`, `search`, `social`
- `alt` ∈ `{"image", "photo", "picture", "logo", "icon", "banner", "avatar"}`
- Rendered bounding box: width < 200 OR height < 100 OR area < 50,000 px² (~224×224)

Survivors are sorted by rendered area descending. The top 15 are screenshotted and
downloaded (full-res to `assets/`, element screenshot to `assets/__pending/`).
Any beyond 15 are logged in the manifest under `skipped_figures` with their source
URL and area. A stdout warning is printed when the cap is triggered.

The area gate is primary — it catches decorative wide/short banners (e.g. 317×72 px
= 22,824 px² fails) while passing content diagrams (600×400 = 240,000 px² passes).

## Chart handling

| Strategy | Trigger | Script action | Agent action |
|---|---|---|---|
| 1 (inline JS config) | Chart.js / Plotly / Highcharts detected in `<script>` | `extract_charts.py` parses config → stored in manifest `chart_config` | Render config as markdown table in `> [CHART:]` block, append to document |
| 2 (canvas / no data) | `<canvas>` present, Strategy 1 extracted nothing | Screenshot canvas → `assets/__pending/chart-NN.png` | Vision-transcribe axes/series/values |

Supported libraries: Chart.js, Highcharts, Plotly, ApexCharts, Google Charts, Vega, ECharts.
Strategy 1 parsing implemented for: Chart.js, Plotly, Highcharts.

## Phase 2: agent orchestration protocol

1. Run the Phase 1 script. Read the output summary.
2. For each `raw/web/<slug>/.fetch-manifest.json`:
   a. `status: complete_pdf` or `status: complete_no_figures` — no agent work needed; mark done.
   b. `status: ready_for_vision`:
      - For each figure in `figures[]`:
        - If `chart_config` is set → render from JSON (exact, no vision needed) → append
          `> [CHART: <title or "Chart">]` block with a markdown table to the document body.
        - Else → Read the PNG at `screenshot` path (vision) → produce a block:
          ```
          ![<short title>](assets/<hash>.ext)

          > [DIAGRAM: <full text description of every label, axis, value, and caption visible in the image>]
          ```
          Always include the `![...](assets/<hash>.ext)` line — it renders the image inline
          and lets the user navigate directly to the asset. Use `original_asset` from the
          manifest for the path (e.g. `assets/01e4fb97912f.png`).
          Replace the `<!--FIG:<id>-->` placeholder in `index.md` with this block.
        - **Orphaned figures** (figure in manifest but no matching `<!--FIG:-->` in the text,
          which happens with attached images on social posts): append a `### Attached Media`
          section at the end of the document and add the block there.
      - After all figures: delete `assets/__pending/` directory.
      - Update `index.md` frontmatter: `transcribed: true`.
   c. `status: blocked` — see Chrome DevTools MCP protocol below.
3. Update `inbox.md`: move done URLs to `## Done` with
   `- [x] <url> → \`raw/web/<slug>/\` (<today>)`.
4. Report: per-URL method, figures transcribed, blocked items, failures.

## Chrome DevTools MCP protocol (blocked URLs)

For each URL with `status: blocked`, after user confirmation (never batch unattended):

1. `mcp__plugin_chrome-devtools-mcp_chrome-devtools__navigate_page` → the blocked URL
2. `mcp__plugin_chrome-devtools-mcp_chrome-devtools__wait_for` → selector `article, main, [role=main]`, timeout 10s
3. `mcp__plugin_chrome-devtools-mcp_chrome-devtools__handle_dialog` → dismiss any alert/dialog
4. `mcp__plugin_chrome-devtools-mcp_chrome-devtools__click` → known dismiss-modal selectors (best effort)
5. `mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_snapshot` → accessibility tree (cleaner than innerText for content extraction)
6. `mcp__plugin_chrome-devtools-mcp_chrome-devtools__evaluate_script` → extract img URLs from the rendered DOM
7. For each content image: `mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_screenshot` with `selector` pointing to the element; vision-transcribe inline
8. Write `raw/web/<slug>/index.md` with standard frontmatter, `fetch_method: chrome-devtools-mcp`, `transcribed: true`
9. Move URL to `## Done` in `inbox.md`

X/Twitter: collect the full thread (not just root post). Slug: `<handle>-<tweet-id>`.

**Out of scope**: bypassing login walls, solving CAPTCHAs, scraping at volume.
Never run the Chrome DevTools MCP pass unattended — each URL requires user confirmation.

## Output contract — `raw/web/<slug>/index.md`

```yaml
---
source_url: https://example.com/article
title: "Example Article"
author: Jane Doe                     # optional
published: 2026-04-12                # optional
language: en                         # optional
channel: "Channel Name"              # YouTube only
duration_sec: 3720                   # YouTube only
fetched: 2026-05-20
fetch_method: trafilatura | playwright | chrome-devtools-mcp | yt-dlp-manual | yt-dlp-auto | yt-dlp-auto-<lang>
transcribed: false                   # set to true by agent after Phase 2
figure_count: 3
---

# Example Article

… body …

<!--FIG:img-00-->   ← placeholder before Phase 2

… body continues …

After Phase 2, the placeholder is replaced with:

![Architecture Overview](assets/abc123def456.png)

> [DIAGRAM: Architecture Overview. Full description of all labels, axes, and captions visible.]
```

After Phase 2, `transcribed: true` and all `<!--FIG:N-->` placeholders are replaced.

## Local files (.tmp/)

`.md` and `.pdf` files dropped into `.tmp/` are processed on each run (no inbox entry needed):

| File type | Output | Notes |
|---|---|---|
| `.md` | `raw/docs/<slug>/index.md` | Frontmatter parsed; vault schema applied |
| `.pdf` | `raw/papers/<slug>.pdf` | Binary copy; slug from filename stem |

**For `.md` files:**

1. Read the file; parse any YAML frontmatter.
2. Extract title: frontmatter `title` → first `# Heading` → filename stem.
3. Generate slug from title.
4. Write `raw/docs/<slug>/index.md` with:
   ```yaml
   ---
   source_file: original-filename.md
   title: <title>
   author: <if present>
   source: <if present>
   publish_date: <if present>
   fetched: YYYY-MM-DD
   ---
   ```
5. Delete the file from `.tmp/`.
6. Append `- [x] (local) filename.md → raw/docs/<slug>/ (date)` to `## Done`.

**For `.pdf` files:**

1. Generate slug from filename stem.
2. Copy to `raw/papers/<slug>.pdf`.
3. Delete the file from `.tmp/`.
4. Append `- [x] (local) filename.pdf → raw/papers/<slug>.pdf (date)` to `## Done`.

## YouTube URLs

Any `youtube.com`, `youtu.be`, `m.youtube.com`, or `youtube-nocookie.com` URL is
handled by Phase 1 only — no HTML fetch, no Playwright, no Phase 2 needed.

**Subtitle ladder:**

1. Manual subtitles (`--write-sub --sub-langs en,en-orig`) — highest quality.
2. Auto-generated English (`--write-auto-sub --sub-langs en,en-orig`).
3. Original-language fallback — first available auto-caption language.
4. No subtitles → `⚠ no subtitles available`. URL stays unchecked.

**VTT deduplication:** duplicate lines from progressive rendering are removed
(set-based, order preserved).

**Dependency:** `yt-dlp` must be installed separately:

```bash
brew install yt-dlp
```

A missing `yt-dlp` fails only YouTube URLs; other entries process normally.

## Dependencies

```bash
pip install trafilatura requests python-slugify beautifulsoup4 lxml markdownify playwright
python -m playwright install chromium
```

## Operational notes

- **FETCH is always interactive.** Vision transcription requires the agent; cannot run
  unattended. Process in small batches (3–5 URLs) for image-heavy inboxes.
- **Playwright skip.** Static-only pages (good trafilatura text, no candidate images,
  no charts) skip the Playwright pass entirely — no browser overhead.
- **Figure cap.** Pages with many images: first 15 by rendered area are processed;
  the rest are logged in the manifest. A warning is printed to stdout.
- **Walled domains** get one auto headless Playwright attempt. If that's blocked,
  the agent's Chrome DevTools MCP pass requires user confirmation per URL.

## Edge cases

- **Arxiv URLs.** `arxiv.org/abs/<id>`, `arxiv.org/html/<id>`, `arxiv.org/pdf/<id>`
  (with or without `.pdf`, with or without `vN`) → rewritten to `arxiv.org/pdf/<id>.pdf`.
  Slug becomes `arxiv-<id>`.
- **Very large PDFs (>50 MB).** Downloaded with a warning.
- **Duplicate URL.** Already in `## Done` → skipped. Un-check manually to re-fetch.
- **Network timeout.** 20s for HTML, 60s for PDFs. Failures don't block the queue.
- **Legacy inbox sections.** `## Processati` and `## Processed` are automatically
  unified into `## Done` on the next run.
