"""
_strip.py — Boilerplate strip constants and helpers for the inbox fetcher.
"""

from __future__ import annotations

STRIP_TAGS = [
    "nav", "footer", "aside", "script", "style",
    "noscript", "iframe", "form", "button",
]

STRIP_PATTERNS = [
    "nav", "navbar", "navigation", "menu", "breadcrumb",
    "footer", "site-footer", "page-footer",
    "header", "site-header", "page-header", "masthead",
    "sidebar", "side-bar", "widget",
    "ad-", "-ad-", "ads", "advertisement", "promo", "promotion", "sponsor",
    "banner", "popup", "modal", "overlay",
    "cookie", "gdpr", "consent", "privacy-notice",
    "subscribe", "newsletter", "signup", "sign-up", "cta",
    "social", "share", "sharing", "follow-us",
    "comment", "disqus",
    "related", "recommended", "more-posts",
    "search-bar", "searchbox",
    "pagination", "pager",
    "skip-link", "screen-reader", "sr-only", "visually-hidden",
    "back-to-top",
]

PRESERVE_TAGS = {
    "article", "main", "table", "thead", "tbody", "tr", "td", "th",
    "code", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "ul", "ol", "li", "figure", "figcaption",
}

CHART_SIGNATURES = {
    "chartjs":    r"new Chart\s*\(",
    "highcharts": r"Highcharts\.(chart|stockChart|mapChart)\s*\(",
    "plotly":     r"Plotly\.(newPlot|react|plot)\s*\(",
    "apexcharts": r"new ApexCharts\s*\(",
    "google":     r"google\.visualization\.",
    "vega":       r"vegaEmbed\s*\(",
    "echarts":    r"echarts\.init\s*\(",
}

DECORATIVE_NAMES = frozenset({
    "logo", "icon", "avatar", "spinner", "loading",
    "pixel", "tracker", "analytics", "1x1", "arrow",
    "close", "menu", "search", "social",
})

DECORATIVE_ALTS = frozenset({
    # Empty alt is intentionally excluded: large images without alt text are
    # likely content diagrams where the author omitted the attribute.
    # The bounding-box area gate in _screenshot_all_images handles truly tiny
    # decoratives that lack alt text.
    # NOTE: "image", "photo", "picture" intentionally excluded — X/Twitter and other
    # platforms use these as generic alt text for all content images. Rely on area
    # gate to filter decoratives.
    "logo", "icon", "banner", "avatar",
})


def should_strip_element(tag) -> bool:
    """Return True if this BS4 tag is boilerplate."""
    if not hasattr(tag, "name") or tag.name is None:
        return False
    if tag.name in PRESERVE_TAGS:
        return False
    if tag.name in STRIP_TAGS:
        return True
    attrs = getattr(tag, "attrs", None) or {}
    classes = " ".join(attrs.get("class", [])).lower()
    tag_id = (attrs.get("id") or "").lower()
    combined = f"{classes} {tag_id}"
    return any(p in combined for p in STRIP_PATTERNS)


def is_decorative_image(src: str, alt: str) -> bool:
    """Return True if the image is likely decorative / non-content."""
    if not src:
        return True
    if src.startswith("data:image"):
        return True
    src_lower = src.lower()
    basename = src_lower.rsplit("/", 1)[-1].split("?")[0]
    if any(name in basename for name in DECORATIVE_NAMES):
        return True
    if alt.strip().lower() in DECORATIVE_ALTS:
        return True
    return False


def integrity_delta(visible_html_words: int, clean_md_words: int) -> float:
    """Fraction of visible HTML text dropped by extraction (0.0–1.0).

    Compares pre-computed visible-text word count (HTML with script/style/noscript
    stripped) against the markdown's word count. A high value means trafilatura
    discarded a lot of content — typical of JS-rendered pages where the static HTML
    is mostly a shell.

    Call site must strip noise tags from the soup and pass the word count,
    NOT the raw HTML string. This avoids inflating the count with tag names,
    attribute values, and inline JS/CSS.
    """
    if visible_html_words == 0:
        return 0.0
    return max(0.0, (visible_html_words - clean_md_words) / visible_html_words)
