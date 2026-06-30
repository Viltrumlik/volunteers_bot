from app.i18n import locale_keys, other_lang, t


def test_uz_ru_key_parity():
    uz, ru = locale_keys("uz"), locale_keys("ru")
    assert uz == ru, {"only_uz": sorted(uz - ru), "only_ru": sorted(ru - uz)}


def test_format_and_fallback():
    assert "90" in t("uz", "shifts.checkout_ok", minutes=90)
    # unknown key falls back to the key string, never raises
    assert t("uz", "no.such.key") == "no.such.key"
    # unknown language falls back to uz
    assert t("xx", "menu.shifts") == t("uz", "menu.shifts")


def test_other_lang():
    assert other_lang("uz") == "ru"
    assert other_lang("ru") == "uz"
