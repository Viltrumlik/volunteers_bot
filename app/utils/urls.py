"""Validation for admin-supplied inline-button URLs.

Telegram renders these as tappable buttons, so we restrict them to an explicit
scheme allowlist and reject links to internal/loopback hosts. This is defence in
depth (the Telegram client, not the bot, follows the link) and stops an admin from
pasting an ``http://169.254.169.254/...`` style internal URL into a broadcast.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"https", "tg"}
_BLOCKED_HOSTNAMES = {"localhost", "metadata", "metadata.google.internal"}


def is_safe_button_url(url: str) -> bool:
    url = (url or "").strip()
    if not url or len(url) > 2048:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False
    if parsed.scheme == "tg":
        return bool(parsed.path or parsed.netloc)
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTNAMES:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a normal DNS hostname
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved)
