#!/usr/bin/env python3
"""
fetch_inbox.py — Process inbox.md and populate raw/web/ (and raw/papers/ for PDFs).

Usage:
    python fetch_inbox.py                    # uses current dir as vault
    python fetch_inbox.py --vault /path      # explicit vault path
    python fetch_inbox.py --dry-run          # shows what would be done

Reads `inbox.md` from the vault root, finds unchecked URL entries,
fetches each, and writes clean markdown + images to raw/web/<slug>/.
PDFs go to raw/papers/<slug>.pdf.

Idempotent: already-processed URLs are skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urljoin

# --- Dependency check with friendly error -----------------------------------

MISSING_DEPS = []
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

if MISSING_DEPS:
    print("Missing dependencies. Install with:", file=sys.stderr)
    print(f"  pip install {' '.join(MISSING_DEPS)}", file=sys.stderr)
    sys.exit(1)


# --- Data types -------------------------------------------------------------

@dataclass
class InboxEntry:
    url: str
    line_index: int
    raw_line: str


@dataclass
class FetchResult:
    url: str
    ok: bool
    kind: str  # "html" | "pdf" | "failed"
    out_path: Path | None = None
    reason: str | None = None


# --- Constants --------------------------------------------------------------

HTML_TIMEOUT = 20
PDF_TIMEOUT = 60
MAX_PDF_SIZE_MB = 50

USER_AGENT = (
    "Mozilla/5.0 (compatible; InboxFetcher/1.0; "
    "+https://github.com/anthropic/skills)"
)

UNCHECKED_PATTERN = re.compile(r"^- \[ \] (https?://\S+)\s*$")
IMG_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Domains known to block plain HTTP fetchers (auth walls, aggressive
# anti-bot, or JS-only rendering). Skip trafilatura entirely and mark
# the URL for agent-driven Playwright MCP fallback.
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

PLAYWRIGHT_HINT = "try playwright"


# --- Core operations --------------------------------------------------------

def find_unchecked_entries(inbox_text: str) -> list[InboxEntry]:
    """Parse inbox.md and return list of unchecked URL entries.
    
    HTML comments (<!-- ... -->) are stripped before parsing so example
    URLs inside comments are not picked up.
    """
    # Strip HTML comments (including multi-line) before parsing
    stripped = re.sub(r"<!--.*?-->", "", inbox_text, flags=re.DOTALL)
    entries = []
    for i, line in enumerate(stripped.splitlines()):
        match = UNCHECKED_PATTERN.match(line)
        if match:
            entries.append(InboxEntry(
                url=match.group(1).strip(),
                line_index=i,
                raw_line=line,
            ))
    return entries


def is_pdf_url(url: str) -> bool:
    """Heuristic: URL path ends in .pdf."""
    return Path(urlparse(url).path).suffix.lower() == ".pdf"


def is_walled(url: str) -> bool:
    """Preflight check: URL host is in the walled-domain list."""
    host = urlparse(url).netloc.lower()
    return host in WALLED_DOMAINS


def rewrite_url_for_fetch(url: str) -> tuple[str, str | None]:
    """Rewrite a user-supplied URL into a better fetch target.

    Returns (fetch_url, slug_override). When slug_override is non-None
    it is used as the raw-file slug verbatim (bypassing slugify) so
    canonical identifiers like arxiv paper IDs survive intact.

    Arxiv abstract and HTML URLs are rewritten to the PDF endpoint so
    we archive the paper itself instead of the landing page.
    """
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
    """Generate a filesystem-safe slug, preferring the title."""
    if title and title.strip():
        s = slugify(title)[:80]
        if s:
            return s
    host = urlparse(url).netloc.replace("www.", "")
    h = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{slugify(host)}-{h}"


def fetch_pdf(url: str, papers_dir: Path,
              slug_override: str | None = None) -> FetchResult:
    """Download a PDF directly to raw/papers/."""
    try:
        r = requests.get(
            url,
            timeout=PDF_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
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

    return FetchResult(url=url, ok=True, kind="pdf", out_path=out_path)


def fetch_html(url: str, web_dir: Path) -> FetchResult:
    """Fetch an HTML article, extract clean markdown, download images."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return FetchResult(url=url, ok=False, kind="failed",
                           reason=f"fetch returned empty (network / 403 / paywall) — {PLAYWRIGHT_HINT}")

    result = trafilatura.extract(
        downloaded,
        output_format="markdown",
        with_metadata=True,
        include_images=True,
        include_links=True,
        include_tables=True,
    )
    if not result or not result.strip():
        return FetchResult(url=url, ok=False, kind="failed",
                           reason=f"extraction empty (likely paywall or JS-rendered) — {PLAYWRIGHT_HINT}")

    meta = trafilatura.extract_metadata(downloaded)
    title = getattr(meta, "title", None) if meta else None
    author = getattr(meta, "author", None) if meta else None
    pub_date = getattr(meta, "date", None) if meta else None
    language = getattr(meta, "language", None) if meta else None

    slug = slug_from(url, title)
    out_dir = web_dir / slug
    assets_dir = out_dir / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(exist_ok=True)

    md_with_local_images = download_images(result, assets_dir, base_url=url)

    frontmatter_lines = [
        "---",
        f"source_url: {url}",
        f"title: {yaml_escape(title) if title else 'Untitled'}",
    ]
    if author:
        frontmatter_lines.append(f"author: {yaml_escape(author)}")
    if pub_date:
        frontmatter_lines.append(f"published: {pub_date}")
    if language:
        frontmatter_lines.append(f"language: {language}")
    frontmatter_lines.append(f"fetched: {date.today().isoformat()}")
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines) + "\n\n"

    body = f"# {title or 'Untitled'}\n\n{md_with_local_images}\n"
    (out_dir / "index.md").write_text(frontmatter + body, encoding="utf-8")

    return FetchResult(url=url, ok=True, kind="html", out_path=out_dir)


def download_images(md: str, assets_dir: Path, base_url: str) -> str:
    """Download all images referenced in md, rewrite paths to local assets/."""

    def replace(match: re.Match) -> str:
        alt, src = match.group(1), match.group(2)
        # Resolve relative URLs against the page URL
        if not src.startswith(("http://", "https://")):
            src_abs = urljoin(base_url, src)
        else:
            src_abs = src
        try:
            r = requests.get(
                src_abs,
                timeout=HTML_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
        except Exception:
            return match.group(0)  # keep original link on failure

        ext = Path(urlparse(src_abs).path).suffix or ".png"
        if len(ext) > 6:  # weird extension, fallback
            ext = ".png"
        name = hashlib.sha1(src_abs.encode()).hexdigest()[:12] + ext
        (assets_dir / name).write_bytes(r.content)
        return f"![{alt}](assets/{name})"

    return IMG_PATTERN.sub(replace, md)


def yaml_escape(s: str) -> str:
    """Minimal YAML string escape: quote if it contains special chars."""
    if any(c in s for c in ":#\"'\n"):
        return '"' + s.replace('"', '\\"').replace("\n", " ") + '"'
    return s


# --- Inbox rewriting --------------------------------------------------------

def update_inbox(
    inbox_path: Path,
    inbox_text: str,
    results: list[FetchResult],
) -> str:
    """
    Rewrite inbox.md:
    - successful URLs are moved under '## Processati'
    - failed URLs stay unchecked with a ⚠ reason appended inline
    """
    lines = inbox_text.splitlines()
    today = date.today().isoformat()

    # Build result lookup by URL
    result_by_url = {r.url: r for r in results}

    # Remove the processed unchecked lines; collect new "Processati" entries
    new_processed_lines: list[str] = []
    out_lines: list[str] = []

    for line in lines:
        match = UNCHECKED_PATTERN.match(line)
        if not match:
            out_lines.append(line)
            continue

        url = match.group(1).strip()
        if url not in result_by_url:
            out_lines.append(line)
            continue

        result = result_by_url[url]
        if result.ok:
            # vault-relative path for readability
            rel = result.out_path
            new_processed_lines.append(
                f"- [x] {url} → `{rel}` ({today})"
            )
        else:
            out_lines.append(f"- [ ] {url} ⚠ {result.reason}")

    # Ensure "## Processati" section exists; append new entries there
    final_lines = list(out_lines)
    if new_processed_lines:
        if not any(l.strip() == "## Processati" for l in final_lines):
            if final_lines and final_lines[-1].strip():
                final_lines.append("")
            final_lines.append("## Processati")
            final_lines.append("")

        # Find the section and append at the end of it (end of file is fine)
        # Simple approach: append to the very end
        final_lines.extend(new_processed_lines)

    return "\n".join(final_lines) + ("\n" if inbox_text.endswith("\n") else "")


# --- Orchestration ----------------------------------------------------------

def process_vault(vault: Path, dry_run: bool = False) -> int:
    inbox_path = vault / "inbox.md"
    if not inbox_path.exists():
        print(f"ERROR: inbox.md not found at {inbox_path}", file=sys.stderr)
        return 1

    web_dir = vault / "raw" / "web"
    papers_dir = vault / "raw" / "papers"

    inbox_text = inbox_path.read_text(encoding="utf-8")
    entries = find_unchecked_entries(inbox_text)

    if not entries:
        print("Inbox empty. Nothing to do.")
        return 0

    print(f"Found {len(entries)} URL(s) to process.")
    if dry_run:
        for e in entries:
            print(f"  would fetch: {e.url}")
        return 0

    results: list[FetchResult] = []
    for e in entries:
        fetch_url, slug_override = rewrite_url_for_fetch(e.url)
        if fetch_url != e.url:
            print(f"\n→ {e.url}\n  (fetching as → {fetch_url})")
        else:
            print(f"\n→ {e.url}")

        if is_pdf_url(fetch_url):
            r = fetch_pdf(fetch_url, papers_dir, slug_override=slug_override)
        elif is_walled(fetch_url):
            host = urlparse(fetch_url).netloc.lower()
            r = FetchResult(
                url=fetch_url, ok=False, kind="failed",
                reason=f"walled domain ({host}) — {PLAYWRIGHT_HINT}",
            )
        else:
            r = fetch_html(fetch_url, web_dir)

        # Track by the original inbox URL, not the rewritten fetch URL,
        # so update_inbox can match the line back.
        r.url = e.url
        results.append(r)
        if r.ok:
            print(f"  ✓ {r.kind} → {r.out_path}")
        else:
            print(f"  ⚠ {r.reason}")

    new_text = update_inbox(inbox_path, inbox_text, results)
    inbox_path.write_text(new_text, encoding="utf-8")

    # Summary
    n_html = sum(1 for r in results if r.ok and r.kind == "html")
    n_pdf = sum(1 for r in results if r.ok and r.kind == "pdf")
    n_fail = sum(1 for r in results if not r.ok)
    print()
    print(f"Processed {len(results)} URLs:")
    print(f"  ✓ {n_html} HTML article(s) → raw/web/")
    print(f"  ✓ {n_pdf} PDF(s) → raw/papers/")
    if n_fail:
        print(f"  ⚠ {n_fail} failed (see inbox.md for reasons)")

    return 0 if n_fail == 0 else 2  # 2 = partial success


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch URLs from inbox.md into raw/ as markdown."
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=Path.cwd(),
        help="Path to vault root (default: current directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List URLs that would be fetched, don't download.",
    )
    args = parser.parse_args()

    if not args.vault.is_dir():
        print(f"ERROR: vault path is not a directory: {args.vault}",
              file=sys.stderr)
        return 1

    return process_vault(args.vault, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
