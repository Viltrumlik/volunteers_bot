from app.database.models import User
from app.security.rbac import Permission, has_any_role_db, has_permission, role_grants


def _u(role: str, tid: int = 1) -> User:
    return User(telegram_id=tid, full_name="x", role=role)


def test_role_grants_user():
    g = role_grants(999, _u("user"))
    assert Permission.user_basic in g
    assert Permission.admin_panel not in g
    assert Permission.super_admin not in g


def test_role_grants_volunteer():
    g = role_grants(999, _u("volunteer"))
    assert Permission.volunteer in g and Permission.admin_panel not in g


def test_role_grants_admin_and_super():
    ga = role_grants(999, _u("admin"))
    assert Permission.admin_panel in ga and Permission.volunteer in ga
    gs = role_grants(999, _u("super_admin"))
    assert Permission.super_admin in gs and Permission.admin_panel in gs


def test_env_privilege_overrides(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("SUPER_ADMIN_IDS", "4242")
    get_settings.cache_clear()
    try:
        g = role_grants(4242, None)
        assert Permission.super_admin in g and Permission.admin_panel in g
    finally:
        get_settings.cache_clear()


def test_has_permission_and_role_db():
    u = _u("admin")
    assert has_permission(1, u, Permission.admin_panel)
    assert has_any_role_db(u, "admin", "super_admin")
    assert not has_any_role_db(None, "admin")
