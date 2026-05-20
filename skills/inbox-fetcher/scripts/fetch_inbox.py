#!/usr/bin/env python3
"""
fetch_inbox.py — Phase 1 of the inbox-fetcher-vision two-phase hybrid.

Sources processed:
  - inbox.md: unchecked URLs → raw/web/ (HTML/YouTube) or raw/papers/ (PDF)
  - .tmp/:     local .md files → raw/docs/<slug>/

Phase 2 is agent-orchestrated: the agent reads each .fetch-manifest.json,
vision-transcribes figures (replacing <!--FIG:N--> placeholders), and runs
the Chrome DevTools MCP interactive pass for URLs marked as blocked.

Usage:
    python fetch_inbox.py                    # uses current dir as vault
    python fetch_inbox.py --vault /path      # explicit vault path
    python fetch_inbox.py --dry-run          # shows what would be done

Idempotent for URLs: already-processed URLs (marked [x]) are skipped.
Local files in .tmp/ are always processed and deleted on success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Ensure sibling scripts are importable regardless of cwd
sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------

MISSING_DEPS: list[str] = []
try:
    import requests
except ImportError:
    MISSING_DEPS.append("requests")
try:
    import trafilatura
except ImportError:
    MISSING_DEPS.append("trafilatura")
try:
    from slugify import slugify
except ImportError:
    MISSING_DEPS.append("python-slugify")
try:
    from bs4 import BeautifulSoup
except ImportError:
    MISSING_DEPS.append("beautifulsoup4")
try:
    import markdownify as _markdownify
except ImportError:
    MISSING_DEPS.append("markdownify")
try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    MISSING_DEPS.append("playwright")

if MISSING_DEPS:
    print("Missing dependencies. Install with:", file=sys.stderr)
    print(f"  pip install {' '.join(MISSING_DEPS)}", file=sys.stderr)
    if "playwright" in MISSING_DEPS:
        print("  python -m playwright install chromium", file=sys.stderr)
    sys.exit(1)

from _strip import (  # noqa: E402
    CHART_SIGNATURES,
    integrity_delta,
    is_decorative_image,
    should_strip_element,
)
from extract_charts import extract_charts  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HTML_TIMEOUT = 20
PDF_TIMEOUT = 60
MAX_PDF_SIZE_MB = 50
MAX_FIGURES_PER_PAGE = 15

MIN_IMG_AREA = 50_000    # px² (~224×224); filters small decoratives
MIN_IMG_WIDTH = 200
MIN_IMG_HEIGHT = 100

PLAYWRIGHT_WAIT_MS = 3500
PLAYWRIGHT_SCRIPT_SNIPPET_LEN = 8_000

USER_AGENT = (
    "Mozilla/5.0 (compatible; InboxFetcherVision/1.0; "
    "+https://github.com/anthropic/skills)"
)

UNCHECKED_PATTERN = re.compile(r"^- \[ \] (https?://\S+)\s*$")
# Handles URLs with balanced parentheses (e.g. Webflow CDN filenames like "(1).avif")
IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(((?:[^()]+|\([^()]*\))*)\)")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)

AUTH_WALL_PATTERN = re.compile(
    r"log\s*in|sign\s*in|create\s+account|subscribe\s+to\s+(read|continue)",
    re.IGNORECASE,
)

WALLED_DOMAINS = frozenset({
    "x.com",
    "twitter.com",
    "mobile.twitter.com",
    "threads.net",
    "linkedin.com",
    "www.linkedin.com",
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "instagram.com",
    "www.instagram.com",
})

CHROME_DEVTOOLS_HINT = "chrome-devtools-mcp"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class InboxEntry:
    url: str
    line_index: int
    raw_line: str


@dataclass
class LocalEntry:
    path: Path
    filename: str


@dataclass
class FigureInfo:
    id: str                         # "img-00", "chart-00", "chart-s1-00"
    kind: str                       # "diagram" | "chart"
    screenshot: str                 # relative path, e.g. "assets/__pending/img-00.png"
    anchor_heading: str | None
    placeholder: str                # "<!--FIG:img-00-->"
    chart_config: dict | None = None
    original_asset: str | None = None       # "assets/<hash>.ext" — full-res archive
    source_url_resolved: str = ""           # absolute, normalized URL (empty for canvas)
    source_url_basename: str = ""           # basename for fallback URL matching
    area: int = 0                           # rendered pixel area, used for sorting


@dataclass
class FetchResult:
    url: str
    ok: bool
    kind: str           # "html" | "pdf" | "youtube" | "local" | "blocked" | "failed"
    out_path: Path | None = None
    reason: str | None = None
    manifest: dict = field(default_factory=dict)

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def find_unchecked_entries(inbox_text: str) -> list[InboxEntry]:
    """Parse inbox.md and return unchecked URL entries, skipping HTML comments."""
    stripped = re.sub(r"<!--.*?-->", "", inbox_text, flags=re.DOTALL)
    entries = []
    for i, line in enumerate(stripped.splitlines()):
        m = UNCHECKED_PATTERN.match(line)
        if m:
            entries.append(InboxEntry(url=m.group(1).strip(), line_index=i, raw_line=line))
    return entries


def is_pdf_url(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() == ".pdf"


def is_walled(url: str) -> bool:
    return urlparse(url).netloc.lower() in WALLED_DOMAINS


def is_youtube_url(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host in {"youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com"}


def rewrite_url_for_fetch(url: str) -> tuple[str, str | None]:
    """Rewrite URLs to reach actual content. Returns (fetch_url, slug_override)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host in ("arxiv.org", "export.arxiv.org"):
        m = re.match(r"^/(?:abs|html|pdf)/(.+?)(?:\.pdf)?$", parsed.path)
        if m:
            paper_id = m.group(1)
            slug = f"arxiv-{paper_id.replace('/', '-')}"
            return f"https://arxiv.org/pdf/{paper_id}.pdf", slug
    return url, None


def slug_from(url: str, title: str | None) -> str:
    if title and title.strip():
        s = slugify(title)[:80]
        if s:
            return s
    host = urlparse(url).netloc.replace("www.", "")
    h = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{slugify(host)}-{h}"


def _twitter_slug(url: str) -> str | None:
    """For X.com/Twitter tweet URLs, return '<handle>-<tweet_id>' slug."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in ("x.com", "twitter.com", "mobile.twitter.com"):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 3 and parts[1] == "status":
        return f"{parts[0]}-{parts[2]}"
    return None


def _clean_social_title(title: str, url: str) -> str:
    """Strip platform-injected cruft from social media page titles.

    X.com format: 'NAME on X: "ARTICLE_TITLE" / X' → 'ARTICLE_TITLE'
    """
    host = urlparse(url).netloc.lower()
    if host in ("x.com", "twitter.com", "mobile.twitter.com"):
        m = re.match(r'^.*? on X:\s*"(.+?)"\s*/\s*X\s*$', title, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()
        return re.sub(r'\s*/\s*X\s*$', '', title).strip()
    return title


def yaml_escape(s: str) -> str:
    if any(c in s for c in ":#\"'\n"):
        return '"' + s.replace('"', '\\"').replace("\n", " ") + '"'
    return s


def _asset_name(src_abs: str) -> str:
    ext = Path(urlparse(src_abs).path).suffix or ".png"
    if len(ext) > 6:
        ext = ".png"
    return hashlib.sha1(src_abs.encode()).hexdigest()[:12] + ext


def _download_image(src_abs: str) -> bytes | None:
    try:
        r = requests.get(src_abs, timeout=HTML_TIMEOUT, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.content
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Local file handling (ported from inbox-fetcher original)
# ---------------------------------------------------------------------------

def scan_tmp_dir(tmp_dir: Path) -> list[LocalEntry]:
    """Return all .md files found in .tmp/. Returns [] if dir is missing."""
    if not tmp_dir.exists():
        return []
    return [LocalEntry(path=p, filename=p.name) for p in sorted(tmp_dir.glob("*.md"))]


def _heading_from_body(body: str) -> str | None:
    """Return text of the first # heading in body, or None."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def extract_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter. Returns (meta_dict, body_without_frontmatter)."""
    if not text.startswith("---"):
        return {}, text
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fm_block = match.group(1)
    body = text[match.end():]
    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def copy_local_file(entry: LocalEntry, docs_dir: Path) -> FetchResult:
    """Copy a local .md file into raw/docs/<slug>/index.md with vault frontmatter."""
    try:
        text = entry.path.read_text(encoding="utf-8")
    except Exception as e:
        return FetchResult(url=entry.filename, ok=False, kind="failed",
                           reason=f"could not read file: {e}")

    meta, body = extract_frontmatter(text)
    title = meta.get("title") or _heading_from_body(body) or entry.path.stem
    author = meta.get("author", "")
    source = meta.get("source", "")
    publish_date = meta.get("publish_date", "") or meta.get("date", "")

    slug = slugify(title)[:80] or slugify(entry.path.stem)[:80] or "untitled"
    out_dir = docs_dir / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    fm_lines = ["---", f"source_file: {entry.filename}", f"title: {yaml_escape(title)}"]
    if author:
        fm_lines.append(f"author: {yaml_escape(author)}")
    if source:
        fm_lines.append(f"source: {yaml_escape(source)}")
    if publish_date:
        fm_lines.append(f"publish_date: {publish_date}")
    fm_lines.append(f"fetched: {date.today().isoformat()}")
    fm_lines.append("---")
    frontmatter = "\n".join(fm_lines) + "\n\n"

    body_stripped = body.strip()
    if body_stripped.startswith("# "):
        content = body_stripped + "\n"
    else:
        content = (f"# {title}\n\n{body_stripped}\n" if body_stripped else f"# {title}\n")

    (out_dir / "index.md").write_text(frontmatter + content, encoding="utf-8")

    try:
        entry.path.unlink()
    except Exception as e:
        print(f"  ⚠ could not delete {entry.filename} from .tmp/: {e}")

    return FetchResult(url=entry.filename, ok=True, kind="local", out_path=out_dir)

# ---------------------------------------------------------------------------
# PDF fetch
# ---------------------------------------------------------------------------

def fetch_pdf(url: str, papers_dir: Path, slug_override: str | None = None) -> FetchResult:
    try:
        r = requests.get(url, timeout=PDF_TIMEOUT,
                         headers={"User-Agent": USER_AGENT}, stream=True)
        r.raise_for_status()
    except Exception as e:
        return FetchResult(url=url, ok=False, kind="failed",
                           reason=f"pdf download failed: {e}")

    size = int(r.headers.get("Content-Length", 0))
    if size > MAX_PDF_SIZE_MB * 1024 * 1024:
        print(f"  ⚠ large PDF ({size // 1024 // 1024} MB): {url}")

    slug = slug_override or slug_from(url, None)
    out_path = papers_dir / f"{slug}.pdf"
    papers_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    return FetchResult(url=url, ok=True, kind="pdf", out_path=out_path,
                       manifest={"status": "complete_pdf", "out_path": str(out_path)})

# ---------------------------------------------------------------------------
# YouTube transcript fetch
# ---------------------------------------------------------------------------

def _vtt_to_text(vtt_path: Path) -> str:
    """Convert a WebVTT file to deduplicated plain text."""
    seen: set[str] = set()
    out: list[str] = []
    for line in vtt_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if (not line
                or line.startswith(("WEBVTT", "Kind:", "Language:"))
                or "-->" in line):
            continue
        clean = re.sub(r"<[^>]*>", "", line)
        clean = clean.replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<")
        if clean and clean not in seen:
            out.append(clean)
            seen.add(clean)
    return "\n".join(out)


def _yt_get_meta(url: str) -> dict | None:
    try:
        out = subprocess.check_output(
            ["yt-dlp", "--print",
             "%(title)s|||%(channel)s|||%(upload_date)s|||%(duration)s|||%(id)s",
             url],
            stderr=subprocess.DEVNULL, text=True, timeout=30,
        ).strip()
        parts = out.split("|||")
        if len(parts) != 5:
            return None
        title, channel, upload_date, duration, vid_id = parts
        pub = (f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
               if len(upload_date) == 8 else None)
        return {
            "title": title or None,
            "channel": channel or None,
            "published": pub,
            "duration_sec": int(duration) if duration.isdigit() else None,
            "video_id": vid_id,
        }
    except Exception:
        return None


def _yt_download_subs(url: str, sub_flag: str, langs: str, tmp: Path) -> Path | None:
    try:
        subprocess.run(
            ["yt-dlp", sub_flag, "--sub-langs", langs,
             "--skip-download", "-o", str(tmp / "s"), url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, check=False,
        )
    except Exception:
        return None
    vtts = list(tmp.glob("*.vtt"))
    return vtts[0] if vtts else None


def _yt_original_lang(url: str) -> str | None:
    try:
        out = subprocess.check_output(
            ["yt-dlp", "--list-subs", "--skip-download", url],
            stderr=subprocess.DEVNULL, text=True, timeout=30,
        )
        for line in out.splitlines():
            cols = line.split()
            if not cols:
                continue
            lang = cols[0]
            if lang.startswith("en"):
                continue
            if "vtt" in line:
                return lang
    except Exception:
        pass
    return None


def fetch_youtube_transcript(url: str, web_dir: Path) -> FetchResult:
    """Phase 1: download subtitles via yt-dlp using the manual→auto-en→original-lang ladder."""
    if not shutil.which("yt-dlp"):
        return FetchResult(url=url, ok=False, kind="failed",
                           reason="yt-dlp not installed — run: brew install yt-dlp")

    meta = _yt_get_meta(url)
    if meta is None:
        return FetchResult(url=url, ok=False, kind="failed",
                           reason="yt-dlp failed to fetch video metadata (private/removed/restricted?)")

    slug = slug_from(url, meta["title"])
    out_dir = web_dir / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)

        vtt = _yt_download_subs(url, "--write-sub", "en,en-orig", tmp)
        fetch_method = "yt-dlp-manual"

        if vtt is None:
            vtt = _yt_download_subs(url, "--write-auto-sub", "en,en-orig", tmp)
            fetch_method = "yt-dlp-auto"

        if vtt is None:
            orig_lang = _yt_original_lang(url)
            if orig_lang:
                vtt = _yt_download_subs(url, "--write-auto-sub", orig_lang, tmp)
                fetch_method = f"yt-dlp-auto-{orig_lang}"

        if vtt is None:
            return FetchResult(url=url, ok=False, kind="failed",
                               reason="no subtitles available (manual, auto-en, or original-lang)")

        body = _vtt_to_text(vtt)

    extra: dict = {}
    if meta.get("channel"):
        extra["channel"] = meta["channel"]
    if meta.get("duration_sec") is not None:
        extra["duration_sec"] = meta["duration_sec"]

    _write_output(
        out_dir=out_dir, url=url, slug=slug, md_body=body,
        title=meta["title"], author=meta["channel"],
        pub_date=meta["published"], language="en",
        text_source=fetch_method, figures=[], skipped_figures=[],
        extra_frontmatter=extra,
    )

    return FetchResult(url=url, ok=True, kind="youtube", out_path=out_dir,
                       manifest={"slug": slug, "figures": 0})

# ---------------------------------------------------------------------------
# BS4 / visual signal analysis (operates on pre-parsed soup)
# ---------------------------------------------------------------------------

def _get_chart_signals(soup) -> dict:
    """Detect chart library signatures and canvas elements.

    Must be called BEFORE decomposing <script> tags in the soup.
    """
    if soup is None:
        return {"has_canvas": False, "canvas_count": 0,
                "detected_libs": [], "script_snippet": ""}
    canvases = soup.find_all("canvas")
    scripts = soup.find_all("script")
    script_text = " ".join(s.get_text() for s in scripts if not s.get("src"))
    detected_libs = [
        lib for lib, pat in CHART_SIGNATURES.items()
        if re.search(pat, script_text)
    ]
    return {
        "has_canvas": bool(canvases),
        "canvas_count": len(canvases),
        "detected_libs": detected_libs,
        "script_snippet": script_text[:PLAYWRIGHT_SCRIPT_SNIPPET_LEN],
    }


def _get_candidate_images(soup, base_url: str) -> list[dict]:
    """Heuristic pre-filter: images in static HTML that might be content.

    Must be called BEFORE decomposing tags. Does not apply the bounding-box
    gate (that requires a live rendered DOM); this is a cheap pre-check used
    to decide whether to launch Playwright at all.
    """
    candidates = []
    for tag in soup.find_all("img"):
        src = tag.get("src") or tag.get("data-src") or ""
        alt = tag.get("alt", "")
        if not src or is_decorative_image(src, alt):
            continue
        abs_src = urljoin(base_url, src) if not src.startswith(("http://", "https://")) else src
        candidates.append({"url": abs_src, "alt": alt})
    return candidates

# ---------------------------------------------------------------------------
# Playwright render + visual track
# ---------------------------------------------------------------------------

def _dismiss_modals(page) -> None:
    """Best-effort: close common modal/cookie overlays."""
    for selector in [
        'button[aria-label="Close"]',
        '[aria-label*="close" i]',
        ".modal-close",
        '[data-testid*="close" i]',
    ]:
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                el.click(timeout=1000)
        except Exception:
            pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _is_auth_wall(page, response_status: int | None) -> bool:
    if response_status in (401, 403):
        return True
    try:
        content = page.content()
    except Exception:
        return False
    soup = BeautifulSoup(content, "lxml")
    main_text = ""
    for sel in ["article", "main", "[role=main]"]:
        el = soup.select_one(sel)
        if el:
            main_text = el.get_text()
            break
    if not main_text:
        main_text = soup.get_text()
    if len(main_text.split()) >= 150:
        return False
    has_password = bool(soup.select('input[type="password"]'))
    has_login_testid = bool(soup.select('[data-testid*="login"]'))
    has_login_text = bool(AUTH_WALL_PATTERN.search(main_text[:2000]))
    return has_password or has_login_testid or has_login_text


def _rendered_markdown(page) -> str:
    """Extract clean markdown from the currently-rendered Playwright page."""
    content = page.content()
    soup = BeautifulSoup(content, "lxml")
    # Focus on the main content area to avoid sidebars, profile widgets, etc.
    # Falls back to the full document if no standard container is found.
    root = (
        soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.find("main")
        or soup
    )
    for tag in list(root.find_all(True)):
        if should_strip_element(tag):
            tag.decompose()
    md = _markdownify.markdownify(
        str(root),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "nav", "footer"],
    )
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    # Strip bare relative timestamps leaked from social media post headers (e.g. "2h", "1d")
    md = re.sub(r"(?m)^\d+[smhdw]\s*$", "", md)
    # Strip social engagement boilerplate that appears at the end of LinkedIn posts
    md = re.sub(r"(?si)\bto view or add a comment\b.*", "", md)
    # Strip LinkedIn reaction bar images (no-alt images in list items just before comment section)
    md = re.sub(r"(?m)^- !\[No alternative text description for this image\]\([^)]*\)\s*$", "", md)
    # Strip X.com top boilerplate (noscript login wall leaked into rendered output)
    md = re.sub(r"(?si)don't miss what's happening.*?(?=\n{2,}|\Z)", "", md)
    md = re.sub(r"(?si)did someone say\s*[…\.]+\s*cookies\?.*?(?=\n{2,}|\Z)", "", md)
    md = re.sub(r"(?m)^\[Log in\]\(/login\)\s*$", "", md)
    md = re.sub(r"(?m)^\[Sign up\]\(/i/flow/signup\)\s*$", "", md)
    md = re.sub(r"(?m)^#\s*$", "", md)   # bare "#" headings with no text
    # Strip X.com footer boilerplate
    md = re.sub(r"(?si)\bwant to publish your own article\?.*", "", md)
    md = re.sub(r"(?si)\bnew to x\?.*", "", md)
    md = re.sub(r"(?si)\btrending now\b.*", "", md)
    # Strip X.com post header boilerplate (profile avatar, name link, handle link, view count)
    # These appear as standalone lines: [![](img)](/handle), [Name](/handle), [@h](/handle), [258K](.../analytics)
    md = re.sub(r"(?m)^\[!\[[^\]]*\]\([^)]+\)\]\(/\w+\)\s*$", "", md)
    md = re.sub(r"(?m)^\[[\w][\w\s.'-]*\]\(/\w+\)\s*$", "", md)
    md = re.sub(r"(?m)^\[@[\w.]+\]\(/[\w/-]+\)\s*$", "", md)
    md = re.sub(r"(?m)^\[\d[\d.,KkMmBb]*\]\([^)]+analytics[^)]*\)\s*$", "", md)
    # Strip LinkedIn profile avatar (linked image whose alt starts with "View profile")
    md = re.sub(r"(?mi)^\[!\[view profile[^\]]*\]\([^)]+\)\]\([^)]+\)\s*$", "", md)
    # Strip LinkedIn "Edited" post marker
    md = re.sub(r"(?m)^Edited\s*$", "", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def _screenshot_all_images(
    page,
    pending_dir: Path,
    assets_dir: Path,
    fig_counter: list[int],
    base_url: str,
) -> tuple[list[FigureInfo], list[dict]]:
    """
    Query the live Playwright DOM for all img elements.

    Pipeline:
    1. Heuristic triage (decorative name/alt filter)
    2. Bounding-box area gate (MIN_IMG_AREA / MIN_IMG_WIDTH / MIN_IMG_HEIGHT)
    3. Sort survivors by area descending (largest = most likely content first)
    4. Cap at MAX_FIGURES_PER_PAGE; screenshot only the selected ones

    Returns (selected_figures, skipped_figures_manifest_entries).
    """
    candidates: list[dict] = []
    try:
        elements = page.query_selector_all("img")
    except Exception:
        return [], []

    seen_srcs: set[str] = set()

    for el in elements:
        # Read the raw HTML attribute first for reproducible URL matching;
        # fall back to the JS-resolved src only if the attribute is absent.
        try:
            raw_src: str = el.evaluate(
                "el => el.getAttribute('src') || el.getAttribute('data-src') || ''"
            )
        except Exception:
            continue
        if not raw_src:
            try:
                raw_src = el.evaluate("el => el.src || el.currentSrc || ''")
            except Exception:
                continue

        if not raw_src or raw_src.startswith("data:"):
            continue

        abs_src = (
            urljoin(base_url, raw_src)
            if not raw_src.startswith(("http://", "https://"))
            else raw_src
        )
        if abs_src in seen_srcs:
            continue
        seen_srcs.add(abs_src)

        try:
            alt: str = el.get_attribute("alt") or ""
        except Exception:
            alt = ""

        if is_decorative_image(abs_src, alt):
            continue

        try:
            bbox = el.bounding_box()
        except Exception:
            continue
        if bbox is None:
            continue
        w, h = bbox.get("width", 0), bbox.get("height", 0)
        if w < MIN_IMG_WIDTH or h < MIN_IMG_HEIGHT or w * h < MIN_IMG_AREA:
            continue

        candidates.append({
            "el": el,
            "abs_src": abs_src,
            "basename": Path(urlparse(abs_src).path).name,
            "alt": alt,
            "area": int(w * h),
        })

    # Sort by area descending — largest figures are most likely to contain content
    candidates.sort(key=lambda c: c["area"], reverse=True)
    selected = candidates[:MAX_FIGURES_PER_PAGE]
    skipped = candidates[MAX_FIGURES_PER_PAGE:]

    if skipped:
        print(f"  ⚠ {len(candidates)} candidate figure(s), capped to {MAX_FIGURES_PER_PAGE} "
              f"(by area). {len(skipped)} skipped (see manifest).")

    figures: list[FigureInfo] = []
    for cand in selected:
        el = cand["el"]
        abs_src = cand["abs_src"]

        content = _download_image(abs_src)
        if content is None:
            continue
        name = _asset_name(abs_src)
        (assets_dir / name).write_bytes(content)

        fig_id = f"img-{fig_counter[0]:02d}"
        fig_counter[0] += 1
        pending_path = pending_dir / f"{fig_id}.png"
        try:
            el.screenshot(path=str(pending_path))
        except Exception:
            continue

        figures.append(FigureInfo(
            id=fig_id,
            kind="diagram",
            screenshot=f"assets/__pending/{fig_id}.png",
            anchor_heading=None,
            placeholder=f"<!--FIG:{fig_id}-->",
            original_asset=f"assets/{name}",
            source_url_resolved=abs_src,
            source_url_basename=cand["basename"],
            area=cand["area"],
        ))

    skipped_manifest = [
        {"src": c["abs_src"], "area": c["area"], "reason": "cap_exceeded"}
        for c in skipped
    ]
    return figures, skipped_manifest


def _screenshot_canvas(
    page,
    pending_dir: Path,
    fig_counter: list[int],
) -> list[FigureInfo]:
    """Screenshot canvas elements for Strategy 2 chart handling."""
    figures: list[FigureInfo] = []
    try:
        canvases = page.query_selector_all("canvas")
    except Exception:
        return figures

    for canvas in canvases:
        try:
            bbox = canvas.bounding_box()
        except Exception:
            continue
        if bbox is None:
            continue
        w, h = bbox.get("width", 0), bbox.get("height", 0)
        if w * h < MIN_IMG_AREA:
            continue

        fig_id = f"chart-{fig_counter[0]:02d}"
        fig_counter[0] += 1
        pending_path = pending_dir / f"{fig_id}.png"
        try:
            canvas.screenshot(path=str(pending_path))
        except Exception:
            continue

        figures.append(FigureInfo(
            id=fig_id,
            kind="chart",
            screenshot=f"assets/__pending/{fig_id}.png",
            anchor_heading=None,
            placeholder=f"<!--FIG:{fig_id}-->",
        ))
    return figures


def _run_playwright_pass(
    url: str,
    need_text: bool,
    chart_signals: dict,
    assets_dir: Path,
    pending_dir: Path,
) -> dict:
    """
    Single Playwright session per URL.

    Returns dict with keys:
      text (str|None), figures (list[FigureInfo]), skipped_figures (list[dict]),
      chart_configs (list[dict]), blocked (bool), blocked_reason (str|None)

    Note: networkidle is intentionally avoided — it times out on analytics-heavy
    pages. domcontentloaded + a fixed wait is the production-safe alternative.
    """
    result: dict = {
        "text": None,
        "page_title": None,
        "figures": [],
        "skipped_figures": [],
        "chart_configs": [],
        "blocked": False,
        "blocked_reason": None,
    }

    if not _PLAYWRIGHT_AVAILABLE:
        result["blocked"] = True
        result["blocked_reason"] = "playwright not installed"
        return result

    pending_dir.mkdir(parents=True, exist_ok=True)

    with _sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)

        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            status = resp.status if resp else None
        except Exception as e:
            result["blocked"] = True
            result["blocked_reason"] = f"playwright navigate failed: {e}"
            browser.close()
            return result

        page.wait_for_timeout(PLAYWRIGHT_WAIT_MS)
        _dismiss_modals(page)

        try:
            result["page_title"] = page.title()
        except Exception:
            pass

        if _is_auth_wall(page, status):
            result["blocked"] = True
            result["blocked_reason"] = "login wall"
            browser.close()
            return result

        if need_text:
            result["text"] = _rendered_markdown(page)

        # Scroll to trigger lazy-loaded images, then wait for loads to settle
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
        except Exception:
            pass

        fig_counter = [0]

        sel_figs, skipped = _screenshot_all_images(
            page, pending_dir, assets_dir, fig_counter, url
        )
        result["figures"].extend(sel_figs)
        result["skipped_figures"].extend(skipped)

        # Chart Strategy 1: extract inline JS config
        if chart_signals.get("detected_libs"):
            configs = extract_charts(
                chart_signals["script_snippet"],
                chart_signals["detected_libs"],
            )
            result["chart_configs"] = configs

        # Chart Strategy 2: canvas screenshot (fallback when no JS config extracted)
        if chart_signals.get("has_canvas") and not result["chart_configs"]:
            canvas_figs = _screenshot_canvas(page, pending_dir, fig_counter)
            result["figures"].extend(canvas_figs)

        browser.close()

    return result

# ---------------------------------------------------------------------------
# Markdown placeholder injection
# ---------------------------------------------------------------------------

def _build_markdown_with_placeholders(
    md: str,
    base_url: str,
    assets_dir: Path,
    figures_by_url: dict[str, FigureInfo],
    figures_by_basename: dict[str, FigureInfo],
) -> str:
    """
    Walk IMG_PATTERN matches in md.
    - Figure images (identified by resolved URL or basename fallback): replace with placeholder.
    - Non-figure images: download and rewrite to local assets/ path.

    Cascading match order:
    1. Full resolved URL (exact)
    2. URL path basename (handles CDN host rewrites)
    """
    def replace(match: re.Match) -> str:
        alt, src = match.group(1), match.group(2)
        abs_src = (
            urljoin(base_url, src)
            if not src.startswith(("http://", "https://"))
            else src
        )
        basename = Path(urlparse(abs_src).path).name

        fig = figures_by_url.get(abs_src) or figures_by_basename.get(basename)
        if fig:
            return fig.placeholder

        content = _download_image(abs_src)
        if content is None:
            return match.group(0)
        name = _asset_name(abs_src)
        (assets_dir / name).write_bytes(content)
        return f"![{alt}](assets/{name})"

    return IMG_PATTERN.sub(replace, md)

# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_output(
    out_dir: Path,
    url: str,
    slug: str,
    md_body: str,
    title: str | None,
    author: str | None,
    pub_date: str | None,
    language: str | None,
    text_source: str,
    figures: list[FigureInfo],
    skipped_figures: list[dict],
    extra_frontmatter: dict | None = None,
) -> None:
    """Write draft index.md and .fetch-manifest.json for Phase 2 consumption."""
    title = title or "Untitled"

    # Current-vault frontmatter schema: source_url / fetched
    fm_lines = [
        "---",
        f"source_url: {url}",
        f"title: {yaml_escape(title)}",
    ]
    if author:
        fm_lines.append(f"author: {yaml_escape(author)}")
    if pub_date:
        fm_lines.append(f"published: {pub_date}")
    if language:
        fm_lines.append(f"language: {language}")
    if extra_frontmatter:
        for k, v in extra_frontmatter.items():
            fm_lines.append(f"{k}: {yaml_escape(str(v))}")
    # Count only figures whose placeholder was actually injected into the markdown body.
    # Figures captured by Playwright but whose img URL didn't match any tag in the text
    # (e.g. decorative photos on pages where they're not inline) are excluded.
    injected_count = sum(1 for f in figures if f.placeholder in md_body)
    fm_lines += [
        f"fetched: {date.today().isoformat()}",
        f"fetch_method: {text_source}",
        "transcribed: false",
        f"figure_count: {injected_count}",
        "---",
    ]
    frontmatter = "\n".join(fm_lines) + "\n\n"

    # Strip leading lines that repeat the title (Playwright pages often include the
    # page <title> as a visible text paragraph at the very top of the rendered output).
    clean_body = md_body.strip()
    t = title.strip()
    body_lines = clean_body.split("\n")
    while body_lines:
        first = body_lines[0].strip()
        if not first:
            body_lines.pop(0)
        elif first == t or first.startswith(t) or (t and t in first and len(first) < len(t) + 20):
            body_lines.pop(0)
        else:
            break
    clean_body = "\n".join(body_lines).strip()

    # Don't prepend # title if:
    # - the body already opens with a heading, OR
    # - the title text already appears in the body (social posts, rendered pages where
    #   the first paragraph IS the title sentence)
    title_start = title.strip()[:50].lower()
    title_in_body = any(
        line.strip().lstrip("#").strip().lower().startswith(title_start)
        for line in clean_body.split("\n")
        if line.strip() and not line.strip().startswith(("!", "[!["))
    )
    if clean_body.startswith("# ") or title_in_body:
        body = clean_body + "\n"
    else:
        body = f"# {title}\n\n{clean_body}\n"

    (out_dir / "index.md").write_text(frontmatter + body, encoding="utf-8")

    all_figs = [
        {
            "id": f.id,
            "kind": f.kind,
            "screenshot": f.screenshot,
            "anchor_heading": f.anchor_heading,
            "placeholder": f.placeholder,
            "chart_config": f.chart_config,
            "original_asset": f.original_asset,
            "source_url": f.source_url_resolved,
        }
        for f in figures
    ]

    manifest = {
        "url": url,
        "slug": slug,
        "out_dir": str(out_dir),
        "status": "ready_for_vision" if all_figs else "complete_no_figures",
        "text_source": text_source,
        "title": title,
        "author": author,
        "published": pub_date,
        "language": language,
        "figures": all_figs,
        "skipped_figures": skipped_figures,
        "blocked": None,
    }
    (out_dir / ".fetch-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_blocked(out_dir: Path, url: str, slug: str, reason: str) -> None:
    """Write .fetch-manifest.json for a blocked URL (no draft index.md written)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "url": url,
        "slug": slug,
        "out_dir": str(out_dir),
        "status": "blocked",
        "text_source": None,
        "title": None,
        "author": None,
        "published": None,
        "language": None,
        "figures": [],
        "skipped_figures": [],
        "blocked": {"reason": reason, "host": urlparse(url).netloc},
    }
    (out_dir / ".fetch-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

# ---------------------------------------------------------------------------
# Main HTML fetch logic
# ---------------------------------------------------------------------------

def fetch_html_hybrid(url: str, web_dir: Path) -> FetchResult:
    """
    Hybrid fetch for an HTML URL.

    Track 1 (text):   trafilatura → Playwright fallback.
    Track 2 (visual): conditional — Playwright launched only when at least one of:
      - text quality is insufficient (< 200 words or integrity_delta >= 30%)
      - static HTML contains candidate content images
      - static HTML contains chart library signatures or <canvas> elements

    For purely textual static pages (no images, no charts, good text extraction)
    Playwright is skipped entirely, keeping fetch time minimal.
    """
    # Step 1: raw HTML via trafilatura's fetcher
    downloaded = trafilatura.fetch_url(url)
    raw_html = downloaded or ""

    # Step 2: trafilatura text extraction
    traf_md = None
    meta = None
    if downloaded:
        traf_md = trafilatura.extract(
            downloaded,
            output_format="markdown",
            with_metadata=False,
            include_images=True,
            include_links=True,
            include_tables=True,
        )
        meta = trafilatura.extract_metadata(downloaded)
    traf_words = len((traf_md or "").split())

    # Step 3: parse static HTML once — reused for signals AND visible word count.
    # Order matters: get chart/image signals BEFORE decomposing <script> tags.
    soup_static = BeautifulSoup(raw_html, "lxml") if raw_html else None

    chart_signals: dict = {"has_canvas": False, "canvas_count": 0,
                           "detected_libs": [], "script_snippet": ""}
    candidate_images_static: list[dict] = []
    if soup_static:
        chart_signals = _get_chart_signals(soup_static)           # needs <script>
        candidate_images_static = _get_candidate_images(soup_static, url)  # needs <img>
        # Strip noise tags for accurate visible word count
        for tag in soup_static(["script", "style", "noscript"]):
            tag.decompose()

    visible_words = (
        len(soup_static.get_text(" ", strip=True).split()) if soup_static else 0
    )

    # Step 4: decide whether Playwright is needed at all
    idelta = integrity_delta(visible_words, traf_words)
    need_playwright_text = (not traf_md or traf_words < 200 or idelta >= 0.30)
    has_chart_signals = bool(
        chart_signals.get("detected_libs") or chart_signals.get("has_canvas")
    )
    need_playwright = (
        need_playwright_text
        or bool(candidate_images_static)
        or has_chart_signals
    )

    # Step 5: metadata from trafilatura
    title = getattr(meta, "title", None) if meta else None
    author = getattr(meta, "author", None) if meta else None
    pub_date = getattr(meta, "date", None) if meta else None
    language = getattr(meta, "language", None) if meta else None

    # Deduplicate author names: trafilatura sometimes concatenates the same name
    # from multiple HTML signals → "Jake Saper Jake Saper Jake Saper" → "Jake Saper"
    if author:
        parts = author.split()
        n = len(parts)
        for unit_len in range(1, n // 2 + 1):
            unit = parts[:unit_len]
            if n % unit_len == 0 and parts == unit * (n // unit_len):
                author = " ".join(unit)
                break

    # For X/Twitter, derive slug from URL — static HTML title is always garbage
    slug = _twitter_slug(url) or slug_from(url, title)
    out_dir = web_dir / slug
    assets_dir = out_dir / "assets"
    pending_dir = assets_dir / "__pending"
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(exist_ok=True)

    # Step 6: Playwright pass (single session, only when needed)
    pw_text: str | None = None
    figures: list[FigureInfo] = []
    skipped_figures: list[dict] = []
    chart_configs: list[dict] = []

    if need_playwright:
        pw_result = _run_playwright_pass(
            url=url,
            need_text=need_playwright_text,
            chart_signals=chart_signals,
            assets_dir=assets_dir,
            pending_dir=pending_dir,
        )

        if pw_result["blocked"]:
            _write_blocked(out_dir, url, slug, pw_result["blocked_reason"] or "unknown")
            return FetchResult(
                url=url, ok=False, kind="blocked",
                out_path=out_dir,
                reason=f"login wall — {CHROME_DEVTOOLS_HINT}",
            )

        pw_text = pw_result["text"]
        figures = pw_result["figures"]
        skipped_figures = pw_result["skipped_figures"]
        chart_configs = pw_result["chart_configs"]

        # For walled domains the static title is often garbage (e.g. "JavaScript is
        # not available."). Override with the rendered page title when it's better.
        _bad_titles = frozenset({
            "javascript is not available.", "sign in", "log in",
            "access denied", "just a moment...", "x",
        })
        pw_title = (pw_result.get("page_title") or "").strip(" .")
        if pw_title and pw_title.lower() not in _bad_titles:
            title = pw_title

    # Strip platform-injected title patterns (e.g. X.com " / X" suffix)
    if title:
        title = _clean_social_title(title, url)

    # Step 7: choose final text source
    if not need_playwright_text and traf_md:
        text_source = "trafilatura"
        md_text = traf_md
    elif pw_text:
        text_source = "playwright"
        md_text = pw_text
    elif traf_md:
        # Playwright was needed for text but produced nothing; fall back
        text_source = "trafilatura"
        md_text = traf_md
    else:
        return FetchResult(
            url=url, ok=False, kind="failed",
            reason=f"extraction empty (network / 403 / paywall) — {CHROME_DEVTOOLS_HINT}",
        )

    # Step 8: replace figure image refs in markdown with <!--FIG:N--> placeholders.
    # Cascading match: full resolved URL first, then basename fallback (CDN rewrites).
    figures_by_url = {f.source_url_resolved: f for f in figures if f.source_url_resolved}
    figures_by_basename = {f.source_url_basename: f for f in figures if f.source_url_basename}

    md_with_placeholders = _build_markdown_with_placeholders(
        md_text, url, assets_dir, figures_by_url, figures_by_basename
    )

    # Step 9: wrap chart Strategy-1 configs as FigureInfo for the manifest.
    # These don't appear as img tags in markdown; the agent renders them from JSON
    # and appends the > [CHART:] block to the document body.
    chart_s1_figs = [
        FigureInfo(
            id=f"chart-s1-{i:02d}",
            kind="chart",
            screenshot="",
            anchor_heading=None,
            placeholder=f"<!--FIG:chart-s1-{i:02d}-->",
            chart_config=c,
        )
        for i, c in enumerate(chart_configs)
    ]
    all_figures = figures + chart_s1_figs
    injected_figures_count = sum(
        1 for f in all_figures if f.placeholder in md_with_placeholders
    )

    # Step 10: write draft index.md + manifest
    _write_output(
        out_dir=out_dir, url=url, slug=slug,
        md_body=md_with_placeholders,
        title=title, author=author, pub_date=pub_date, language=language,
        text_source=text_source, figures=all_figures,
        skipped_figures=skipped_figures,
    )

    return FetchResult(
        url=url, ok=True, kind="html", out_path=out_dir,
        manifest={"slug": slug, "figures": injected_figures_count},
    )

# ---------------------------------------------------------------------------
# Inbox rewriting
# ---------------------------------------------------------------------------

def _normalize_done_section(text: str) -> str:
    """Unify ## Processati / ## Processed / ## Done into a single ## Done section."""
    # Rename legacy header if ## Done is absent
    if "## Processati" in text and "## Done" not in text:
        text = text.replace("## Processati", "## Done", 1)
    elif "## Processed" in text and "## Done" not in text:
        text = text.replace("## Processed", "## Done", 1)

    # If both a legacy header AND ## Done coexist, merge legacy content into ## Done
    for legacy in ("## Processati", "## Processed"):
        if legacy not in text or "## Done" not in text:
            continue
        lines = text.splitlines(keepends=True)
        legacy_idx = next(
            (i for i, l in enumerate(lines) if l.strip() == legacy), None
        )
        if legacy_idx is None:
            continue
        next_section = next(
            (i for i in range(legacy_idx + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        legacy_content = lines[legacy_idx + 1: next_section]
        del lines[legacy_idx: next_section]

        done_idx = next(
            (i for i, l in enumerate(lines) if l.strip() == "## Done"), None
        )
        if done_idx is None:
            text = "".join(lines)
            continue
        done_end = next(
            (i for i in range(done_idx + 1, len(lines)) if lines[i].startswith("## ")),
            len(lines),
        )
        for j, content_line in enumerate(legacy_content):
            lines.insert(done_end + j, content_line)
        text = "".join(lines)

    return text


def update_inbox(
    inbox_path: Path,
    inbox_text: str,
    url_results: list[FetchResult],
    local_results: list[FetchResult] | None = None,
) -> str:
    today = date.today().isoformat()
    inbox_text = _normalize_done_section(inbox_text)
    lines = inbox_text.splitlines()
    result_by_url = {r.url: r for r in url_results}
    new_done_lines: list[str] = []
    out_lines: list[str] = []

    for line in lines:
        m = UNCHECKED_PATTERN.match(line)
        if not m:
            out_lines.append(line)
            continue
        url = m.group(1).strip()
        if url not in result_by_url:
            out_lines.append(line)
            continue
        r = result_by_url[url]
        if r.ok:
            new_done_lines.append(f"- [x] {url} → `{r.out_path}` ({today})")
        else:
            out_lines.append(f"- [ ] {url} ⚠ {r.reason}")

    if local_results:
        for r in local_results:
            if r.ok:
                new_done_lines.append(
                    f"- [x] (local) {r.url} → `{r.out_path}` ({today})"
                )

    final_lines = list(out_lines)
    if new_done_lines:
        if not any(l.strip() == "## Done" for l in final_lines):
            if final_lines and final_lines[-1].strip():
                final_lines.append("")
            final_lines.append("## Done")
            final_lines.append("")
        final_lines.extend(new_done_lines)

    return "\n".join(final_lines) + ("\n" if inbox_text.endswith("\n") else "")

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def process_vault(vault: Path, dry_run: bool = False) -> int:
    inbox_path = vault / "inbox.md"
    if not inbox_path.exists():
        print(f"ERROR: inbox.md not found at {inbox_path}", file=sys.stderr)
        return 1

    web_dir = vault / "raw" / "web"
    papers_dir = vault / "raw" / "papers"
    docs_dir = vault / "raw" / "docs"
    tmp_dir = vault / ".tmp"

    inbox_text = inbox_path.read_text(encoding="utf-8")
    url_entries = find_unchecked_entries(inbox_text)
    local_entries = scan_tmp_dir(tmp_dir)

    if not url_entries and not local_entries:
        print("Inbox empty. Nothing to do.")
        return 0

    print(f"Found {len(url_entries)} URL(s) and {len(local_entries)} local file(s).")

    if dry_run:
        for e in url_entries:
            print(f"  would fetch URL: {e.url}")
        for e in local_entries:
            print(f"  would copy local: {e.filename}")
        return 0

    # --- URL processing ---
    url_results: list[FetchResult] = []
    for e in url_entries:
        fetch_url, slug_override = rewrite_url_for_fetch(e.url)
        if fetch_url != e.url:
            print(f"\n→ {e.url}\n  (fetching as → {fetch_url})")
        else:
            print(f"\n→ {e.url}")

        if is_pdf_url(fetch_url):
            r = fetch_pdf(fetch_url, papers_dir, slug_override=slug_override)
        elif is_youtube_url(fetch_url):
            print("  ▶ youtube — fetching transcript via yt-dlp")
            r = fetch_youtube_transcript(fetch_url, web_dir)
        elif is_walled(fetch_url):
            # Try headless Playwright first; mark blocked only if auth wall detected
            print("  ⚠ walled domain — attempting headless Playwright first")
            r = fetch_html_hybrid(fetch_url, web_dir)
            if not r.ok and r.kind != "blocked":
                host = urlparse(fetch_url).netloc.lower()
                r = FetchResult(
                    url=fetch_url, ok=False, kind="blocked",
                    reason=f"walled domain ({host}) — {CHROME_DEVTOOLS_HINT}",
                )
        else:
            r = fetch_html_hybrid(fetch_url, web_dir)

        r.url = e.url
        url_results.append(r)

        if r.ok:
            figs = r.manifest.get("figures", 0) if r.manifest else 0
            print(f"  ✓ {r.kind} → {r.out_path}"
                  + (f" ({figs} figure(s) pending vision)" if figs else ""))
        elif r.kind == "blocked":
            print(f"  ⚠ blocked: {r.reason}")
        else:
            print(f"  ⚠ {r.reason}")

    # --- Local file processing ---
    local_results: list[FetchResult] = []
    for e in local_entries:
        print(f"\n→ (local) {e.filename}")
        r = copy_local_file(e, docs_dir)
        local_results.append(r)
        if r.ok:
            print(f"  ✓ local → {r.out_path}")
        else:
            print(f"  ⚠ {r.reason}")

    # --- Update inbox ---
    new_text = update_inbox(inbox_path, inbox_text, url_results, local_results)
    inbox_path.write_text(new_text, encoding="utf-8")

    # --- Summary ---
    n_html = sum(1 for r in url_results if r.ok and r.kind == "html")
    n_pdf = sum(1 for r in url_results if r.ok and r.kind == "pdf")
    n_yt = sum(1 for r in url_results if r.ok and r.kind == "youtube")
    n_local = sum(1 for r in local_results if r.ok)
    n_blocked = sum(1 for r in url_results if r.kind == "blocked")
    n_fail = sum(
        1 for r in [*url_results, *local_results] if not r.ok and r.kind == "failed"
    )

    print()
    print(f"Processed {n_html + n_pdf + n_yt + n_local} item(s):")
    if n_html:
        print(f"  ✓ {n_html} HTML article(s) → raw/web/")
    if n_pdf:
        print(f"  ✓ {n_pdf} PDF(s) → raw/papers/")
    if n_yt:
        print(f"  ✓ {n_yt} YouTube transcript(s) → raw/web/")
    if n_local:
        print(f"  ✓ {n_local} local file(s) → raw/docs/")
    if n_blocked:
        print(f"  ⚠ {n_blocked} blocked (login wall) — agent Chrome DevTools MCP pass required")
    if n_fail:
        print(f"  ⚠ {n_fail} failed (see inbox.md for reasons)")
    print()
    print("Phase 1 complete. Run the agent FETCH phase to vision-transcribe figures.")

    return 0 if (n_fail == 0 and n_blocked == 0) else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 1: fetch URLs from inbox.md and local .md files from .tmp/ into raw/. "
            "Phase 2 (agent) vision-transcribes figures and handles blocked URLs via "
            "Chrome DevTools MCP."
        )
    )
    parser.add_argument(
        "--vault", type=Path, default=Path.cwd(),
        help="Path to vault root (default: current directory).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List items that would be processed without downloading.",
    )
    args = parser.parse_args()

    if not args.vault.is_dir():
        print(f"ERROR: vault path is not a directory: {args.vault}", file=sys.stderr)
        return 1

    return process_vault(args.vault, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
