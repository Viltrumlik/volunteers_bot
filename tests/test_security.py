import importlib

from app.logging_config import mask_user_id
from app.utils.sanitize import sanitize_user_text, strip_invisible
from app.utils.urls import is_safe_button_url


def test_button_url_allowlist():
    assert is_safe_button_url("https://example.com/x")
    assert is_safe_button_url("tg://resolve?domain=foo")
    assert not is_safe_button_url("http://example.com")  # http not allowed
    assert not is_safe_button_url("javascript:alert(1)")
    assert not is_safe_button_url("https://localhost/admin")
    assert not is_safe_button_url("https://169.254.169.254/latest/meta-data")
    assert not is_safe_button_url("https://127.0.0.1")
    assert not is_safe_button_url("")


def test_sanitize_escapes_html():
    out = sanitize_user_text('<b>x</b> & "q"')
    assert "<b>" not in out and "&lt;b&gt;" in out and "&amp;" in out


def test_strip_invisible():
    assert strip_invisible("a​b﻿c") == "abc"


def test_mask_user_id_is_stable_and_not_raw():
    m1 = mask_user_id(123456789)
    m2 = mask_user_id(123456789)
    assert m1 == m2 and m1.startswith("u#") and "123456789" not in m1
    assert mask_user_id(None) == "anon"


def test_api_auth_fail_closed_and_keyed(monkeypatch):
    from app.config import get_settings

    # Without API_KEY -> fail closed (503)
    get_settings.cache_clear()
    import app.api.main as api

    importlib.reload(api)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    assert client.get("/health").status_code == 200
    assert client.get("/health").headers.get("X-Content-Type-Options") == "nosniff"
    assert client.get("/metrics/summary").status_code == 503

    # With API_KEY -> 401 without/with wrong header, 200 with correct
    monkeypatch.setenv("API_KEY", "s3cr3t")
    get_settings.cache_clear()
    importlib.reload(api)
    client = TestClient(api.app)
    assert client.get("/metrics/summary").status_code == 401
    assert client.get("/metrics/summary", headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/metrics/summary", headers={"X-API-Key": "s3cr3t"}).status_code == 200
    get_settings.cache_clear()
