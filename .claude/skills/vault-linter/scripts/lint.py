#!/usr/bin/env python3
"""
lint.py — Deterministic health check for a second brain vault (v4).

Runs deterministic checks against the wiki and writes a report.
No LLM. Standard library only.

Usage:
    python lint.py                    # uses cwd as vault
    python lint.py --vault /path      # explicit vault root
    python lint.py --unattended       # no prompts, suitable for schedulers
    python lint.py --quiet            # minimal stdout, full report in file

Exit codes:
    0 — clean (no findings)
    1 — findings present (expected; not a failure)
    2 — script error (filesystem, bug, etc.)

Output:
    .lint/report.md    human-readable findings grouped by severity
    .lint/state.yaml   bookkeeping (last run date, counters)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


# --- Constants --------------------------------------------------------------

WIKI_SUBDIRS = ("pages", "sources", "views")
STALE_SOURCE_DAYS = 180
VIEW_STALE_DAYS = 30
DUPLICATE_SIMILARITY_THRESHOLD = 0.75

# Files allowed to be "orphan" (no incoming wiki links)
ORPHAN_EXCEPTIONS = {
    "wiki/hot.md",
    "wiki/compass.md",
    "wiki/index.md",
    "wiki/log.md",
    "index.md",
    "log.md",
}

# Required frontmatter fields per type
REQUIRED_FRONTMATTER = {
    "source": {"type", "source_path", "created", "updated"},
    "page": {"type", "created", "updated"},
    "view": {"type", "kind", "created", "updated", "based_on"},
}

# Patterns
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
# Heuristic: capitalized multi-word phrases in prose (very rough proper-noun detector)
PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")


# --- Data types -------------------------------------------------------------

@dataclass
class Finding:
    severity: str  # "blocking" | "important" | "advisory"
    check: str
    file: str
    detail: str
    line: int | None = None


@dataclass
class WikiPage:
    path: Path         # absolute path
    rel: str           # vault-relative, forward slashes
    type: str | None   # from frontmatter
    frontmatter: dict[str, str] = field(default_factory=dict)
    title: str | None = None
    outgoing_links: list[tuple[str, int]] = field(default_factory=list)  # (target, line)
    body_text: str = ""


# --- Utilities --------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict[str, str | list], str]:
    """Minimal YAML-like parser: scalars + simple lists.
    
    Supports:
        key: value              → scalar string
        key: [a, b, c]          → list
        key:                    → list (if followed by `- item` lines)
          - a
          - b
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    block = match.group(1)
    body = text[match.end():].lstrip("\n")

    fm: dict[str, str | list] = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Case: inline list
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            items = [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
            fm[key] = items
            i += 1
            continue

        # Case: empty value, expect block list in following indented lines
        if value == "":
            items = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if not nxt.strip():
                    j += 1
                    continue
                # block list item
                if re.match(r"^\s+-\s+", nxt):
                    item = re.sub(r"^\s+-\s+", "", nxt).strip()
                    # strip quotes
                    if (item.startswith('"') and item.endswith('"')) or \
                       (item.startswith("'") and item.endswith("'")):
                        item = item[1:-1]
                    items.append(item)
                    j += 1
                else:
                    break
            if items:
                fm[key] = items
            else:
                fm[key] = ""
            i = j
            continue

        # Case: scalar with optional quotes
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        fm[key] = value
        i += 1

    return fm, body


def normalize_link_target(target: str, vault_root: Path, source_file: Path) -> Path | None:
    """Resolve a [[link]] target into an absolute path, or None if unresolvable.

    Rules:
    - Try target as-is (vault-relative, then source-relative).
    - If not found, also try with .md appended — slugs like
      arxiv-2602.20867 look like they have an extension but don't.
    - This way both [[wiki/sources/foo]] and [[wiki/sources/foo.md]] work,
      and slugs containing dots resolve correctly.
    """
    target = target.strip()
    if not target:
        return None

    base = Path(target)
    candidates = [base]
    if base.suffix != ".md":
        candidates.append(base.with_name(base.name + ".md"))

    # Try each candidate vault-relative, then source-relative.
    for cand in candidates:
        abs_vault = vault_root / cand
        if abs_vault.exists():
            return abs_vault
        abs_local = source_file.parent / cand
        if abs_local.exists():
            return abs_local.resolve()

    # Fall back to first candidate vault-relative (for error reporting).
    return vault_root / candidates[0]


def slugify(s: str) -> str:
    """Simple slug: lowercase, keep alphanumerics, replace rest with -."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def jaccard(a: str, b: str) -> float:
    """Jaccard similarity on whitespace-normalized token sets."""
    ta = set(re.split(r"[-_\s]+", a.lower()))
    tb = set(re.split(r"[-_\s]+", b.lower()))
    ta = {t for t in ta if t}
    tb = {t for t in tb if t}
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union)


def title_similarity(a: str, b: str) -> float:
    """Combined similarity: max of Jaccard over tokens and character-level
    overlap. Catches cases like 'agent-skill' vs 'agent-skills' where
    token Jaccard is low (singular/plural) but strings are nearly identical."""
    j = jaccard(slugify(a), slugify(b))
    # Character-level: shorter normalized, check prefix containment
    sa = slugify(a).replace("-", "")
    sb = slugify(b).replace("-", "")
    if not sa or not sb:
        return j
    short, long = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    # If shorter is a near-prefix of longer (allow 1 char diff)
    if len(long) - len(short) <= 2 and long.startswith(short):
        return max(j, 0.85)
    return j


def parse_date(s: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


# --- Loading ----------------------------------------------------------------

def load_wiki(vault: Path) -> dict[str, WikiPage]:
    """Load all markdown files under wiki/. Keys are vault-relative paths."""
    pages: dict[str, WikiPage] = {}
    wiki_root = vault / "wiki"
    if not wiki_root.is_dir():
        return pages

    for md_file in wiki_root.rglob("*.md"):
        rel = md_file.relative_to(vault).as_posix()
        text = md_file.read_text(encoding="utf-8", errors="replace")
        fm, body = parse_frontmatter(text)

        page = WikiPage(
            path=md_file,
            rel=rel,
            type=fm.get("type"),
            frontmatter=fm,
            title=extract_title(body) or md_file.stem,
            body_text=body,
        )

        # Extract outgoing links with line numbers
        for line_no, line in enumerate(body.splitlines(), start=1):
            for m in WIKILINK_RE.finditer(line):
                target = m.group(1)
                page.outgoing_links.append((target, line_no))

        pages[rel] = page

    return pages


def extract_title(body: str) -> str | None:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


# --- Checks -----------------------------------------------------------------

def check_dead_links(pages: dict[str, WikiPage], vault: Path) -> list[Finding]:
    findings = []
    for page in pages.values():
        for target, line in page.outgoing_links:
            resolved = normalize_link_target(target, vault, page.path)
            if resolved is None or not resolved.exists():
                findings.append(Finding(
                    severity="blocking",
                    check="dead_links",
                    file=page.rel,
                    line=line,
                    detail=f"[[{target}]] does not resolve to an existing file",
                ))
    return findings


def check_orphans(pages: dict[str, WikiPage], vault: Path) -> list[Finding]:
    # Build incoming-link map
    incoming: dict[str, int] = defaultdict(int)
    for page in pages.values():
        for target, _ in page.outgoing_links:
            resolved = normalize_link_target(target, vault, page.path)
            if resolved and resolved.exists():
                try:
                    rel = resolved.relative_to(vault).as_posix()
                    incoming[rel] += 1
                except ValueError:
                    continue

    findings = []
    for rel, page in pages.items():
        if rel in ORPHAN_EXCEPTIONS:
            continue
        # Views are leaf nodes in the graph — they cite sources via
        # based_on, so they're not expected to have incoming links.
        if page.type == "view":
            continue
        if incoming.get(rel, 0) == 0:
            findings.append(Finding(
                severity="important",
                check="orphans",
                file=rel,
                detail="no incoming wiki links",
            ))
    return findings


def check_duplicates(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []
    # Compare titles within same subdir only (pages vs pages, views vs views)
    by_subdir: dict[str, list[WikiPage]] = defaultdict(list)
    for page in pages.values():
        parts = page.rel.split("/")
        if len(parts) >= 2 and parts[0] == "wiki":
            by_subdir[parts[1]].append(page)

    seen_pairs = set()
    for subdir, group in by_subdir.items():
        for i, p1 in enumerate(group):
            for p2 in group[i + 1:]:
                t1 = p1.title or p1.path.stem
                t2 = p2.title or p2.path.stem
                sim = title_similarity(t1, t2)
                if sim >= DUPLICATE_SIMILARITY_THRESHOLD:
                    pair = tuple(sorted([p1.rel, p2.rel]))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    findings.append(Finding(
                        severity="advisory",
                        check="duplicates",
                        file=p1.rel,
                        detail=f"similar to {p2.rel} (jaccard={sim:.2f})",
                    ))
    return findings


def check_missing_metadata(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []
    for page in pages.values():
        # Catalog files (index.md, log.md, hot.md, compass.md) are
        # exempt — they're not typed content, they're bookkeeping.
        if page.rel in ORPHAN_EXCEPTIONS:
            continue
        page_type = page.type
        if not page_type:
            findings.append(Finding(
                severity="blocking",
                check="missing_metadata",
                file=page.rel,
                detail="no 'type' field in frontmatter",
            ))
            continue
        required = REQUIRED_FRONTMATTER.get(page_type, set())
        missing = required - set(page.frontmatter.keys())
        if missing:
            findings.append(Finding(
                severity="blocking",
                check="missing_metadata",
                file=page.rel,
                detail=f"missing required fields: {', '.join(sorted(missing))}",
            ))
    return findings


def check_inconsistent_naming(pages: dict[str, WikiPage]) -> list[Finding]:
    """Same target linked with different display names."""
    findings = []
    target_to_names: dict[str, set[str]] = defaultdict(set)

    for page in pages.values():
        body = page.body_text
        for m in WIKILINK_RE.finditer(body):
            target = m.group(1).strip()
            name = (m.group(2) or target).strip()
            # Normalize target
            if not target.endswith(".md"):
                target = target + ".md"
            target_to_names[target].add(name)

    for target, names in target_to_names.items():
        if len(names) > 2:  # allow small natural variation
            findings.append(Finding(
                severity="advisory",
                check="inconsistent_naming",
                file=target,
                detail=f"referenced with {len(names)} different names: {sorted(names)}",
            ))
    return findings


def check_stale_sources(pages: dict[str, WikiPage]) -> list[Finding]:
    findings = []
    threshold = date.today() - timedelta(days=STALE_SOURCE_DAYS)
    for page in pages.values():
        if not page.rel.startswith("wiki/sources/"):
            continue
        updated_str = page.frontmatter.get("updated", "")
        updated = parse_date(updated_str)
        if updated and updated < threshold:
            days_old = (date.today() - updated).days
            findings.append(Finding(
                severity="advisory",
                check="stale_sources",
                file=page.rel,
                detail=f"not updated in {days_old} days (since {updated})",
            ))
    return findings


def check_gaps(pages: dict[str, WikiPage]) -> list[Finding]:
    """Heuristic: proper-noun-like phrases in prose that don't correspond to
    a wiki page. Very noisy; marked advisory."""
    findings = []

    # Build a set of known page titles (lowercase) for quick lookup
    known: set[str] = set()
    for page in pages.values():
        if page.title:
            known.add(page.title.lower())
            known.add(slugify(page.title))
        known.add(page.path.stem.lower())

    phrase_counts: Counter[str] = Counter()
    for page in pages.values():
        # Strip wikilinks before counting
        stripped = WIKILINK_RE.sub("", page.body_text)
        for m in PROPER_NOUN_RE.finditer(stripped):
            phrase = m.group(1).strip()
            if phrase.lower() in known or slugify(phrase) in known:
                continue
            phrase_counts[phrase] += 1

    # Only report phrases appearing ≥3 times (reduces noise dramatically)
    for phrase, count in phrase_counts.most_common():
        if count < 3:
            break
        findings.append(Finding(
            severity="advisory",
            check="gaps",
            file="(multiple files)",
            detail=f"'{phrase}' mentioned {count} times but no wiki page exists",
        ))
        if len(findings) >= 10:  # cap noise
            break
    return findings


def check_view_staleness(pages: dict[str, WikiPage]) -> list[Finding]:
    """An evolving view (shareable: false) is stale when its based_on
    pages have been updated significantly after the view's own updated
    date. Shareable views are frozen by design and not checked."""
    findings = []

    for page in pages.values():
        if page.type != "view":
            continue
        # Shareable views are frozen — they're snapshots, not living
        # representations. Staleness doesn't apply to them.
        if str(page.frontmatter.get("shareable", "")).lower() == "true":
            continue

        view_updated = parse_date(page.frontmatter.get("updated", ""))
        if not view_updated:
            continue

        based_on = page.frontmatter.get("based_on", [])
        if not isinstance(based_on, list):
            continue

        stale_deps = []
        for dep in based_on:
            dep_clean = dep.strip().lstrip("[").rstrip("]")
            if "|" in dep_clean:
                dep_clean = dep_clean.split("|", 1)[0]
            dep_path = dep_clean if dep_clean.endswith(".md") else dep_clean + ".md"
            dep_page = pages.get(dep_path)
            if not dep_page:
                continue
            dep_updated = parse_date(dep_page.frontmatter.get("updated", ""))
            if not dep_updated:
                continue
            days_diff = (dep_updated - view_updated).days
            if days_diff > VIEW_STALE_DAYS:
                stale_deps.append(f"{dep_path} (+{days_diff}d)")

        if stale_deps:
            findings.append(Finding(
                severity="advisory",
                check="view_staleness",
                file=page.rel,
                detail=f"based_on pages updated after view: {', '.join(stale_deps)}",
            ))
    return findings


def check_missing_cross_references(pages: dict[str, WikiPage]) -> list[Finding]:
    """Source pages that name an existing page in prose but don't link
    to it. Heuristic — only flags exact title matches."""
    findings = []

    # Build index: lowercase title → relative path, for pages
    title_to_rel: dict[str, str] = {}
    for page in pages.values():
        if page.title and page.rel.startswith("wiki/pages/"):
            title_to_rel[page.title.lower()] = page.rel

    for page in pages.values():
        if not page.rel.startswith("wiki/sources/"):
            continue
        # What does this source already link to?
        linked_titles = set()
        for target, _ in page.outgoing_links:
            target_norm = target if target.endswith(".md") else target + ".md"
            for p in pages.values():
                if p.rel == target_norm:
                    if p.title:
                        linked_titles.add(p.title.lower())

        # Strip wikilinks before scanning prose
        stripped = WIKILINK_RE.sub("", page.body_text).lower()

        for title, target_rel in title_to_rel.items():
            if title in linked_titles:
                continue
            if len(title) < 4:  # skip short titles (too noisy)
                continue
            # Must appear as a whole word
            if re.search(r"\b" + re.escape(title) + r"\b", stripped):
                findings.append(Finding(
                    severity="advisory",
                    check="missing_cross_references",
                    file=page.rel,
                    detail=f"mentions '{title}' in prose but does not link to {target_rel}",
                ))
    return findings


# --- Report -----------------------------------------------------------------

def severity_rank(s: str) -> int:
    return {"blocking": 0, "important": 1, "advisory": 2}.get(s, 3)


def write_report(findings: list[Finding], vault: Path, quiet: bool = False) -> None:
    lint_dir = vault / ".lint"
    lint_dir.mkdir(exist_ok=True)

    by_severity: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_severity[f.severity].append(f)

    lines: list[str] = []
    lines.append(f"# Lint Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")

    counts = {
        "blocking": len(by_severity.get("blocking", [])),
        "important": len(by_severity.get("important", [])),
        "advisory": len(by_severity.get("advisory", [])),
    }
    lines.append(f"**Summary:** {counts['blocking']} blocking · "
                 f"{counts['important']} important · "
                 f"{counts['advisory']} advisory")
    lines.append("")

    if not findings:
        lines.append("✅ Vault is clean. No findings.")
        lines.append("")
    else:
        for severity in ("blocking", "important", "advisory"):
            items = by_severity.get(severity, [])
            if not items:
                continue
            lines.append(f"## {severity.capitalize()} ({len(items)})")
            lines.append("")
            # Group by check
            by_check: dict[str, list[Finding]] = defaultdict(list)
            for f in items:
                by_check[f.check].append(f)
            for check, group in sorted(by_check.items()):
                lines.append(f"### {check} — {len(group)} finding(s)")
                lines.append("")
                for f in group:
                    loc = f":{f.line}" if f.line else ""
                    lines.append(f"- `{f.file}{loc}` — {f.detail}")
                lines.append("")

    report_path = lint_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    if not quiet:
        print(f"Report written to {report_path.relative_to(vault)}")


def write_state(vault: Path, findings: list[Finding], exit_code: int) -> None:
    lint_dir = vault / ".lint"
    lint_dir.mkdir(exist_ok=True)
    state_path = lint_dir / "state.yaml"

    # Preserve ingests counter — this gets reset here because a lint was run
    lines = [
        f"last_lint: {date.today().isoformat()}",
        f"ingests_since_last_lint: 0",
        f"last_exit_code: {exit_code}",
        f"last_findings_count: {len(findings)}",
        f"blocking: {sum(1 for f in findings if f.severity == 'blocking')}",
        f"important: {sum(1 for f in findings if f.severity == 'important')}",
        f"advisory: {sum(1 for f in findings if f.severity == 'advisory')}",
    ]
    state_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Orchestration ----------------------------------------------------------

def run_lint(vault: Path, quiet: bool = False) -> int:
    if not (vault / "wiki").is_dir():
        print(f"ERROR: no wiki/ directory in {vault}", file=sys.stderr)
        return 2

    pages = load_wiki(vault)
    if not quiet:
        print(f"Loaded {len(pages)} wiki pages from {vault}/wiki/")

    all_checks = [
        ("dead_links", check_dead_links),
        ("orphans", check_orphans),
        ("duplicates", check_duplicates),
        ("missing_metadata", check_missing_metadata),
        ("inconsistent_naming", check_inconsistent_naming),
        ("stale_sources", check_stale_sources),
        ("gaps", check_gaps),
        ("view_staleness", check_view_staleness),
        ("missing_cross_references", check_missing_cross_references),
    ]

    findings: list[Finding] = []
    for name, fn in all_checks:
        try:
            # Not all checks accept vault; use signature-based dispatch
            if name in ("dead_links", "orphans"):
                out = fn(pages, vault)
            else:
                out = fn(pages)
        except Exception as e:
            print(f"ERROR in check '{name}': {e}", file=sys.stderr)
            return 2
        findings.extend(out)
        if not quiet:
            print(f"  {name}: {len(out)} finding(s)")

    # Sort: blocking first, then important, then advisory; within, by file
    findings.sort(key=lambda f: (severity_rank(f.severity), f.file, f.line or 0))

    exit_code = 0 if not findings else 1
    write_report(findings, vault, quiet=quiet)
    write_state(vault, findings, exit_code)

    if not quiet:
        counts_str = (
            f"{sum(1 for f in findings if f.severity == 'blocking')} blocking, "
            f"{sum(1 for f in findings if f.severity == 'important')} important, "
            f"{sum(1 for f in findings if f.severity == 'advisory')} advisory"
        )
        print(f"\nDone. {counts_str}.")

    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint a second brain vault. Writes .lint/report.md."
    )
    parser.add_argument(
        "--vault", type=Path, default=Path.cwd(),
        help="Path to vault root (default: current directory).",
    )
    parser.add_argument(
        "--unattended", action="store_true",
        help="No prompts. Suitable for schedulers.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Minimal stdout. Full report still written to .lint/report.md.",
    )
    args = parser.parse_args()

    if not args.vault.is_dir():
        print(f"ERROR: vault path is not a directory: {args.vault}", file=sys.stderr)
        return 2

    # unattended and quiet are compatible; quiet is implied by unattended
    # but we keep them independent for finer control.
    try:
        return run_lint(args.vault.resolve(), quiet=args.quiet or args.unattended)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
