import os
import re
import unicodedata
from datetime import datetime
import pandas as pd
from flask import session

from core.config import BASE_DIR

def normalize_header(value):
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[\s\-_]+", "", text)
    return text

def find_header_row(df):
    for i, row in df.head(30).iterrows():
        joined = " ".join([str(v) for v in row.values])
        cells = [normalize_header(v) for v in row.values]
        if (
            "Nom" in joined
            or "Prenom" in joined
            or "nomcomplet" in "".join(cells)
            or any(c in {"nom", "prenom", "nomcomplet", "nomprenom", "fullname"} for c in cells)
        ):
            return i
    return -1

def build_default_mapping(columns):
    defaults = {
        "full_name": "",
        "last_name": "",
        "first_name": "",
        "classe": "",
        "devoir": "",
        "activite": "",
        "compo": "",
        "participation": "",
        "comportement": "",
        "cahier": "",
        "projet": "",
        "assiduite_outils": "",
        "remarques": "",
        "phone": "",
        "email": "",
    }

    for col in columns:
        norm = normalize_header(col)
        if not defaults["full_name"] and norm in ("nomcomplet", "nomprenom", "fullname"):
            defaults["full_name"] = col
        elif not defaults["last_name"] and norm in ("nom", "lastname", "surname"):
            defaults["last_name"] = col
        elif not defaults["first_name"] and norm in ("prenom", "firstname"):
            defaults["first_name"] = col
        elif not defaults["classe"] and norm in ("classe", "niveau", "class"):
            defaults["classe"] = col
        elif not defaults["devoir"] and norm in ("devoir", "dev", "homework", "04", "4"):
            defaults["devoir"] = col
        elif not defaults["activite"] and norm in ("activite", "act", "activity", "01", "1"):
            defaults["activite"] = col
        elif not defaults["compo"] and norm in ("compo", "composition", "exam", "test", "09", "9"):
            defaults["compo"] = col
        elif not defaults["participation"] and norm in ("participation", "moucharaka", "moucharakah"):
            defaults["participation"] = col
        elif not defaults["comportement"] and norm in ("comportement", "souk", "conduite", "behavior"):
            defaults["comportement"] = col
        elif not defaults["cahier"] and norm in ("cahier", "korras", "kras", "copybook"):
            defaults["cahier"] = col
        elif not defaults["projet"] and norm in ("projet", "project"):
            defaults["projet"] = col
        elif not defaults["assiduite_outils"] and norm in ("absencesoutils", "assiduiteoutils", "absoutils", "outils"):
            defaults["assiduite_outils"] = col
        elif not defaults["remarques"] and norm in ("remarques", "appreciation", "rem", "obs", "commentaire"):
            defaults["remarques"] = col
        elif not defaults["phone"] and norm in ("telephone", "tel", "phone", "mobile"):
            defaults["phone"] = col
        elif not defaults["email"] and norm in ("email", "mail", "e-mail"):
            defaults["email"] = col
    return defaults

def preview_dir():
    path = os.path.join(BASE_DIR, "tmp_imports")
    os.makedirs(path, exist_ok=True)
    return path

def cleanup_import_previews(max_age_seconds=24 * 3600):
    folder = preview_dir()
    now = int(datetime.now().timestamp())
    for name in os.listdir(folder):
        full = os.path.join(folder, name)
        try:
            if not os.path.isfile(full):
                continue
            if now - int(os.path.getmtime(full)) > max_age_seconds:
                os.remove(full)
        except Exception:
            continue

def get_preview_meta(token):
    data = session.get("import_preview") or {}
    if data.get("token") != token:
        return None
    path = data.get("path") or ""
    if not path or not os.path.exists(path):
        return None
    return data

def clear_preview_meta(meta):
    try:
        path = meta.get("path") or ""
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    session.pop("import_preview", None)

def row_value(row, column_name):
    if not column_name:
        return None
    if column_name not in row.index:
        return None
    val = row.get(column_name, None)
    return None if pd.isna(val) else val

def prepare_import_dataframe(raw_df):
    if raw_df is None or raw_df.empty:
        return None, None, False

    header_row = find_header_row(raw_df)
    header_detected = header_row >= 0
    if header_row < 0:
        header_row = 0

    work = raw_df.copy()
    work.columns = work.iloc[header_row]
    work = work.iloc[header_row + 1 :].dropna(how="all").copy()

    # Ensure unique, non-empty column names for robust mapping.
    normalized = []
    seen = {}
    for col in list(work.columns):
        label = str(col).strip() if col is not None else ""
        if not label:
            label = "col"
        base = label
        idx = 2
        while label in seen:
            label = f"{base}_{idx}"
            idx += 1
        seen[label] = 1
        normalized.append(label)
    work.columns = normalized

    return work, int(header_row), header_detected

def resolve_mapped_column(columns, selected):
    if not selected:
        return ""
    if selected in columns:
        return selected
    target = normalize_header(selected)
    for col in columns:
        if normalize_header(col) == target:
            return col
    return ""

def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None
