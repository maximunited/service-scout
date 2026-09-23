"""Apprise digest + optional brain-api memory."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


def send_apprise(urls: list[str], title: str, body: str) -> bool:
    if not urls:
        log.info("apprise_skip_no_urls")
        return False
    try:
        import apprise

        apobj = apprise.Apprise()
        for u in urls:
            apobj.add(u)
        ok = bool(apobj.notify(title=title, body=body))
        log.info("apprise_sent ok=%s", ok)
        return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("apprise_failed: %s", exc)
        return False


def brain_append(
    *,
    api_url: str,
    token: str,
    summary: str,
    agent: str = "service-scout",
    project: str = "service-scout",
    topics: str = "scout",
) -> bool:
    if not api_url or not token:
        return False
    payload: dict[str, Any] = {
        "agent": agent,
        "project": project,
        "summary": summary[:500],
        "topics": topics,
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                api_url,
                json=payload,
                headers={"X-Brain-Token": token, "Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("brain_append_failed: %s", exc)
        return False
