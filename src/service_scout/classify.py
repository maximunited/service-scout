"""Pre-Ollama URL / content classifiers — hard-reject blogs & UI-only tools."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from service_scout.config import OverridesConfig
from service_scout.dedupe import normalize_domain

# Domains that repeatedly produce content/UI false positives (not ingestible APIs).
DEFAULT_DENYLIST_DOMAINS: frozenset[str] = frozenset(
    {
        "tikr.com",
        "www.tikr.com",
        "quant-investing.com",
        "www.quant-investing.com",
        "aswathdamodaran.substack.com",
        "pages.stern.nyu.edu",  # Damodaran static essays / datasets pages (not REST)
    }
)

# Host / path signals that the hit is an article, guide, academy, or newsletter.
_CONTENT_HOST_SUFFIXES = (
    ".substack.com",
    ".medium.com",
    ".ghost.io",
    ".hashnode.dev",
    ".wordpress.com",
    ".blogspot.com",
)

_CONTENT_PATH_RE = re.compile(
    r"(?i)/(blog|blogs|academy|guide|guides|primer|primers|tutorial|tutorials|"
    r"learn|learning|education|newsletter|post|posts|article|articles|"
    r"insights?|explainers?|how-to|howto)(/|$|[?#])"
)

_CONTENT_TITLE_RE = re.compile(
    r"(?i)\b(primer|guide|tutorial|how\s+to|explainer|newsletter|"
    r"academy|blog\s+post|deep\s*dive|what\s+is\s+fcf)\b"
)

# Free web terminal / screener marketing — not a machine-ingestible contract.
_UI_ONLY_HINTS = re.compile(
    r"(?i)\b(terminal|screener|dashboard|web\s*app|sign\s*up\s*free|"
    r"free\s+account|login\s+to\s+(view|access)|interactive\s+chart)\b"
)

# Evidence that something is actually ingestible for PA fetchers.
_INGEST_EVIDENCE_RE = re.compile(
    r"(?i)\b("
    r"rest\s*api|graphql|openapi|swagger|"
    r"json\s*(api|endpoint|feed)|"
    r"public\s*(api|endpoint)|"
    r"free\s*(api|tier|endpoint|key)|"
    r"api\s*key|"
    r"scrapable|scrape|"
    r"/api/v?\d|"
    r"endpoint\s*[:=]"
    r")\b"
)

# Soft "talks about free FCF" is NOT ingest evidence.
_FALSE_FREE_SIGNAL_RE = re.compile(
    r"(?i)\b(free\s+(tools?|guide|primer|essay|account|trial|webinar)|"
    r"learn\s+(how|to)|educational)\b"
)


@dataclass(frozen=True)
class Classification:
    """Result of pre-LLM URL classification."""

    kind: str  # candidate | content_only | ui_only | denylist
    reason: str
    skip_ollama: bool = False


def _host(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    return (urlparse(raw).hostname or "").lower()


def _path(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    return urlparse(raw).path or "/"


def denylist_domains(overrides: OverridesConfig | None = None) -> set[str]:
    out = {d.lower() for d in DEFAULT_DENYLIST_DOMAINS}
    if overrides:
        out |= {d.lower() for d in overrides.force_reject_domains}
    return out


def is_denylisted(url: str, overrides: OverridesConfig | None = None) -> bool:
    domain = normalize_domain(url)
    host = _host(url)
    denied = denylist_domains(overrides)
    for d in denied:
        d = d.lower()
        if not d:
            continue
        if domain == d or host == d or domain.endswith("." + d) or host.endswith("." + d):
            return True
    return False


def is_content_only_url(url: str, title: str = "") -> bool:
    """True for blogs, guides, primers, academy pages — not data sources."""
    host = _host(url)
    path = _path(url)
    if any(host.endswith(sfx) for sfx in _CONTENT_HOST_SUFFIXES):
        return True
    if host in ("medium.com", "substack.com", "dev.to", "towardsdatascience.com"):
        return True
    if _CONTENT_PATH_RE.search(path):
        return True
    if title and _CONTENT_TITLE_RE.search(title) and not has_ingest_evidence(title):
        return True
    return False


def looks_ui_only(url: str, title: str = "", snippets: list[str] | None = None) -> bool:
    """UI terminal / free-account product with no API mention in nearby text."""
    blob = " ".join([title or "", url or "", *(snippets or [])])
    if has_ingest_evidence(blob):
        return False
    return bool(_UI_ONLY_HINTS.search(blob)) and not has_ingest_evidence(blob)


def has_ingest_evidence(text: str) -> bool:
    """Accept requires a machine-ingestible contract signal, not 'free article'."""
    if not text:
        return False
    if _INGEST_EVIDENCE_RE.search(text):
        # Guard: "free guide to using REST conceptually" still OK if REST/API present.
        return True
    return False


def is_false_free_signal(text: str) -> bool:
    """True when text sells free *content/tools* without API evidence."""
    if not text:
        return False
    if has_ingest_evidence(text):
        return False
    return bool(_FALSE_FREE_SIGNAL_RE.search(text))


def classify_candidate(
    url: str,
    *,
    title: str = "",
    snippets: list[str] | None = None,
    overrides: OverridesConfig | None = None,
) -> Classification:
    """
    Pre-Ollama gate. Content-only / denylist → skip Ollama (save credits).
    """
    if is_denylisted(url, overrides):
        return Classification(
            kind="denylist",
            reason="denylist_domain",
            skip_ollama=True,
        )
    if is_content_only_url(url, title=title):
        return Classification(
            kind="content_only",
            reason="not_a_data_source",
            skip_ollama=True,
        )
    blob = " ".join([title or "", *(snippets or [])])
    if is_false_free_signal(blob) and not has_ingest_evidence(blob):
        return Classification(
            kind="content_only",
            reason="content_only_no_api",
            skip_ollama=True,
        )
    if looks_ui_only(url, title=title, snippets=snippets):
        return Classification(
            kind="ui_only",
            reason="ui_only_no_api",
            skip_ollama=True,
        )
    return Classification(kind="candidate", reason="", skip_ollama=False)
