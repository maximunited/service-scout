"""Domain / name → service_id aliases."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_scout.config import OverridesConfig
from service_scout.db import ServiceAlias, domains_list, set_domains


def normalize_domain(url_or_host: str) -> str:
    raw = (url_or_host or "").strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    # Strip common docs/app/api prefixes for alias matching
    for prefix in ("docs.", "api.", "app.", "www.", "developer.", "developers."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
            break
    return host


def name_slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:80] or "unknown"


def make_service_id(name: str, url: str) -> str:
    domain = normalize_domain(url)
    base = domain or name_slug(name)
    digest = hashlib.sha256(f"{base}|{name_slug(name)}".encode()).hexdigest()[:8]
    return f"{base}-{digest}" if domain else f"{name_slug(name)}-{digest}"


def find_alias(
    session: Session,
    *,
    name: str,
    url: str,
    overrides: OverridesConfig | None = None,
) -> ServiceAlias | None:
    domain = normalize_domain(url)
    if overrides and domain in overrides.alias_merges:
        domain = normalize_domain(overrides.alias_merges[domain])

    rows = session.scalars(select(ServiceAlias)).all()
    for row in rows:
        if domain and domain in domains_list(row):
            return row
        if name_slug(name) and name_slug(name) == name_slug(row.canonical_name):
            return row
    return None


def resolve_service_id(
    session: Session,
    *,
    name: str,
    url: str,
    overrides: OverridesConfig | None = None,
) -> str:
    existing = find_alias(session, name=name, url=url, overrides=overrides)
    if existing:
        domain = normalize_domain(url)
        if domain:
            doms = domains_list(existing)
            if domain not in doms:
                set_domains(existing, doms + [domain])
                session.commit()
        return existing.service_id

    domain = normalize_domain(url)
    if overrides and domain in overrides.alias_merges:
        domain = normalize_domain(overrides.alias_merges[domain])

    sid = make_service_id(name, url if not domain else f"https://{domain}")
    alias = ServiceAlias(
        service_id=sid,
        canonical_name=name or domain or sid,
        domains="[]",
    )
    if domain:
        set_domains(alias, [domain])
    session.add(alias)
    session.commit()
    return sid


def is_force_rejected(url: str, overrides: OverridesConfig) -> bool:
    domain = normalize_domain(url)
    return any(domain == d.lower() or domain.endswith("." + d.lower()) for d in overrides.force_reject_domains)
