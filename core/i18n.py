from typing import Optional

from flask import session

SUPPORTED_LANGS = ("fr", "ar")

TRANSLATIONS = {
    "fr": {
        "menu.dashboard": "Tableau",
        "menu.resources": "Ressources",
        "menu.settings": "Parametres",
        "menu.subjects": "Matieres",
        "menu.timetable": "Emploi du temps",
        "menu.history": "Historique",
        "menu.admin": "Admin",
        "menu.profile": "Profil",
        "menu.logout": "Logout",
        "theme.light": "Mode clair",
        "theme.dark": "Mode sombre",
        "lang.switch": "AR",
        "role.read_only": "Lecture seule",
        "role.prof": "Prof",
        "role.admin": "Admin",
        "import.mapping.title": "Import intelligent Excel",
        "import.mapping.subtitle": "Associez les colonnes avant validation.",
        "import.mapping.apply": "Valider import",
        "import.mapping.cancel": "Annuler",
    },
    "ar": {
        "menu.dashboard": "لوحة التحكم",
        "menu.resources": "الموارد",
        "menu.settings": "الإعدادات",
        "menu.subjects": "المواد",
        "menu.timetable": "التوقيت",
        "menu.history": "السجل",
        "menu.admin": "الإدارة",
        "menu.profile": "الملف",
        "menu.logout": "خروج",
        "theme.light": "وضع فاتح",
        "theme.dark": "وضع داكن",
        "lang.switch": "FR",
        "role.read_only": "قراءة فقط",
        "role.prof": "أستاذ",
        "role.admin": "مسؤول",
        "import.mapping.title": "استيراد ذكي من إكسل",
        "import.mapping.subtitle": "طابق الأعمدة قبل التأكيد.",
        "import.mapping.apply": "تأكيد الاستيراد",
        "import.mapping.cancel": "إلغاء",
    },
}


def get_lang() -> str:
    lang = (session.get("lang") or "fr").lower()
    if lang not in SUPPORTED_LANGS:
        return "fr"
    return lang


def get_text_dir(lang: Optional[str] = None) -> str:
    current = lang or get_lang()
    return "rtl" if current == "ar" else "ltr"


def tr(key: str, default: Optional[str] = None, **kwargs) -> str:
    lang = get_lang()
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS["fr"].get(key, default if default is not None else key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
