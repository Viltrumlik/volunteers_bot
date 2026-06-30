from app.i18n import t


def label_set(*keys: str) -> set[str]:
    s: set[str] = set()
    for k in keys:
        s.add(t("uz", k))
        s.add(t("ru", k))
    return s


def all_registered_menu_labels() -> set[str]:
    return label_set(
        "menu.projects",
        "menu.profile",
        "menu.stats",
        "menu.faq",
        "menu.support",
        "menu.suggestion",
        "menu.shifts",
        "menu.hours",
        "menu.broadcast",
        "menu.regions_admin",
        "menu.applications_admin",
        "menu.projects_admin",
        "menu.faq_admin",
        "menu.events_admin",
        "menu.admin_panel",
    )
