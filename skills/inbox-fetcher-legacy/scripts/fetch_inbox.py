#!/usr/bin/env python3
"""
fetch_inbox.py — Process inbox.md and .tmp/ for a second brain vault.

Sources:
  - inbox.md: unchecked URLs → raw/web/ (HTML) or raw/papers/ (PDF)
  - .tmp/: local .md files → raw/docs/<slug>/

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
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urljoin

# --- Dependency check -------------------------------------------------------

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
class LocalEntry:
    path: Path
    filename: str


@dataclass
class FetchResult:
    url: str
    ok: bool
    kind: str  # "html" | "pdf" | "local" | "failed"
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
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)

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


# --- Utilities --------------------------------------------------------------

def yaml_escape(s: str) -> str:
    """Minimal YAML string escape: quote if it contains special chars."""
    if any(c in s for c in ":#\"'\n"):
        return '"' + s.replace('"', '\\"').replace("\n", " ") + '"'
    return s


def extract_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from a markdown file.

    Returns (meta_dict, body_without_frontmatter).
    Simple key: value parsing — no full YAML library required.
    """
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


# --- Local file handling ----------------------------------------------------

def scan_tmp_dir(tmp_dir: Path) -> list[LocalEntry]:
    """Return all .md files found in .tmp/. Returns [] if dir is missing."""
    if not tmp_dir.exists():
        return []
    return [
        LocalEntry(path=p, filename=p.name)
        for p in sorted(tmp_dir.glob("*.md"))
    ]


def _heading_from_body(body: str) -> str | None:
    """Return text of the first # heading in body, or None."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


def copy_local_file(entry: LocalEntry, docs_dir: Path) -> FetchResult:
    """Copy a local .md file into raw/docs/<slug>/index.md.

    Strips the original frontmatter, extracts metadata from it, and
    writes a vault-standard frontmatter. The original file is deleted
    from .tmp/ on success.
    """
    try:
        text = entry.path.read_text(encoding="utf-8")
    except Exception as e:
        return FetchResult(url=entry.filename, ok=False, kind="failed",
                           reason=f"could not read file: {e}")

    meta, body = extract_frontmatter(text)

    # Title: frontmatter > first # heading > filename stem
    title = (
        meta.get("title")
        or _heading_from_body(body)
        or entry.path.stem
    )
    author = meta.get("author", "")
    source = meta.get("source", "")
    publish_date = meta.get("publish_date", "") or meta.get("date", "")

    slug = slugify(title)[:80] or slugify(entry.path.stem)[:80] or "untitled"
    out_dir = docs_dir / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    fm_lines = [
        "---",
        f"source_file: {entry.filename}",
        f"title: {yaml_escape(title)}",
    ]
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
    # Don't duplicate a # heading that's already the first line of body
    if body_stripped.startswith("# "):
        content = body_stripped + "\n"
    else:
        content = (f"# {title}\n\n{body_stripped}\n"
                   if body_stripped else f"# {title}\n")

    (out_dir / "index.md").write_text(frontmatter + content, encoding="utf-8")

    try:
        entry.path.unlink()
    except Exception as e:
        print(f"  ⚠ could not delete {entry.filename} from .tmp/: {e}")

    return FetchResult(url=entry.filename, ok=True, kind="local", out_path=out_dir)


# --- URL operations ---------------------------------------------------------

def find_unchecked_entries(inbox_text: str) -> list[InboxEntry]:
    """Parse inbox.md and return list of unchecked URL entries.

    HTML comments are stripped first so example URLs inside comments
    are not picked up.
    """
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

    fm_lines = [
        "---",
        f"source_url: {url}",
        f"title: {yaml_escape(title) if title else 'Untitled'}",
    ]
    if author:
        fm_lines.append(f"author: {yaml_escape(author)}")
    if pub_date:
        fm_lines.append(f"published: {pub_date}")
    if language:
        fm_lines.append(f"language: {language}")
    fm_lines.append(f"fetched: {date.today().isoformat()}")
    fm_lines.append("---")
    frontmatter = "\n".join(fm_lines) + "\n\n"

    body = f"# {title or 'Untitled'}\n\n{md_with_local_images}\n"
    (out_dir / "index.md").write_text(frontmatter + body, encoding="utf-8")

    return FetchResult(url=url, ok=True, kind="html", out_path=out_dir)


def download_images(md: str, assets_dir: Path, base_url: str) -> str:
    """Download all images referenced in md, rewrite paths to local assets/."""

    def replace(match: re.Match) -> str:
        alt, src = match.group(1), match.group(2)
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
            return match.group(0)
        ext = Path(urlparse(src_abs).path).suffix or ".png"
        if len(ext) > 6:
            ext = ".png"
        name = hashlib.sha1(src_abs.encode()).hexdigest()[:12] + ext
        (assets_dir / name).write_bytes(r.content)
        return f"![{alt}](assets/{name})"

    return IMG_PATTERN.sub(replace, md)


# --- Inbox rewriting --------------------------------------------------------

def _normalize_done_section(text: str) -> str:
    """Unify ## Processati and ## Done into a single ## Done section."""
    has_done = "## Done" in text
    has_processati = "## Processati" in text

    if not has_processati:
        return text

    if not has_done:
        return text.replace("## Processati", "## Done", 1)

    # Both exist: move Processati content into Done, remove Processati header.
    lines = text.splitlines(keepends=True)

    processati_idx = next(
        (i for i, l in enumerate(lines) if l.strip() == "## Processati"), None
    )
    if processati_idx is None:
        return text

    next_section = next(
        (i for i in range(processati_idx + 1, len(lines))
         if lines[i].startswith("## ")),
        len(lines),
    )
    processati_content = lines[processati_idx + 1 : next_section]
    del lines[processati_idx : next_section]

    done_idx = next(
        (i for i, l in enumerate(lines) if l.strip() == "## Done"), None
    )
    if done_idx is None:
        return "".join(lines)

    done_end = next(
        (i for i in range(done_idx + 1, len(lines))
         if lines[i].startswith("## ")),
        len(lines),
    )
    for j, content_line in enumerate(processati_content):
        lines.insert(done_end + j, content_line)

    return "".join(lines)


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
            new_done_lines.append(
                f"- [x] {url} → `{result.out_path}` ({today})"
            )
        else:
            out_lines.append(f"- [ ] {url} ⚠ {result.reason}")

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


# --- Orchestration ----------------------------------------------------------

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

    if dry_run:
        for e in url_entries:
            print(f"  would fetch URL: {e.url}")
        for e in local_entries:
            print(f"  would copy local: {e.filename}")
        return 0

    print(f"Found {len(url_entries)} URL(s) and {len(local_entries)} local file(s).")

    url_results: list[FetchResult] = []
    for e in url_entries:
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

        r.url = e.url
        url_results.append(r)
        if r.ok:
            print(f"  ✓ {r.kind} → {r.out_path}")
        else:
            print(f"  ⚠ {r.reason}")

    local_results: list[FetchResult] = []
    for e in local_entries:
        print(f"\n→ (local) {e.filename}")
        r = copy_local_file(e, docs_dir)
        local_results.append(r)
        if r.ok:
            print(f"  ✓ local → {r.out_path}")
        else:
            print(f"  ⚠ {r.reason}")

    new_text = update_inbox(inbox_path, inbox_text, url_results, local_results)
    inbox_path.write_text(new_text, encoding="utf-8")

    n_html = sum(1 for r in url_results if r.ok and r.kind == "html")
    n_pdf = sum(1 for r in url_results if r.ok and r.kind == "pdf")
    n_local = sum(1 for r in local_results if r.ok)
    n_fail = sum(1 for r in [*url_results, *local_results] if not r.ok)
    total = n_html + n_pdf + n_local

    print()
    print(f"Processed {total} item(s):")
    if n_html:
        print(f"  ✓ {n_html} HTML article(s) → raw/web/")
    if n_pdf:
        print(f"  ✓ {n_pdf} PDF(s) → raw/papers/")
    if n_local:
        print(f"  ✓ {n_local} local file(s) → raw/docs/")
    if n_fail:
        print(f"  ⚠ {n_fail} failed (see inbox.md for details)")

    return 0 if n_fail == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch URLs from inbox.md and .md files from .tmp/ into raw/."
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
        help="List items that would be processed, don't fetch.",
    )
    args = parser.parse_args()

    if not args.vault.is_dir():
        print(f"ERROR: vault path is not a directory: {args.vault}",
              file=sys.stderr)
        return 1

    return process_vault(args.vault, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
