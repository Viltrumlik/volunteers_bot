"""Tiny JSON-backed i18n. Supported languages: ``uz`` (default) and ``ru``.

``t(lang, "ns.key", **fmt)`` walks a dotted path and ``str.format``s the result.
Missing keys fall back to the key string (so the UI degrades visibly, never crashes).
The flattening helpers exist so tests can assert uz/ru key parity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUPPORTED = ("uz", "ru")
DEFAULT = "uz"

_LOCALES = Path(__file__).parent / "locales"
_CACHE: dict[str, dict[str, Any]] = {}


def _load(lang: str) -> dict[str, Any]:
    key = lang if lang in SUPPORTED else DEFAULT
    if key not in _CACHE:
        path = _LOCALES / f"{key}.json"
        with open(path, encoding="utf-8") as f:
            _CACHE[key] = json.load(f)
    return _CACHE[key]


def t(lang: str, key: str, **kwargs: Any) -> str:
    data = _load(lang)
    cur: Any = data
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return key
    if not isinstance(cur, str):
        return key
    try:
        return cur.format(**kwargs) if kwargs else cur
    except (KeyError, IndexError):
        return cur


def other_lang(lang: str) -> str:
    return "ru" if lang == "uz" else "uz"


def flatten_keys(data: dict[str, Any], prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys |= flatten_keys(v, path)
        else:
            keys.add(path)
    return keys


def locale_keys(lang: str) -> set[str]:
    return flatten_keys(_load(lang))
