import csv
import json
import os
import re
import unicodedata
from datetime import datetime
from io import BytesIO, TextIOWrapper

import openpyxl
import pandas as pd
from flask import Blueprint, flash, redirect, render_template, request, send_file, session, url_for

from core.audit import log_change
from core.config import BASE_DIR
from core.db import get_db
from core.security import login_required
from core.utils import clean_note, get_appreciation_dynamique

bp = Blueprint("main", __name__)


def _parse_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _normalize_header(value):
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


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None


def _school_year(now):
    if now.month >= 9:
        return f"{now.year}/{now.year + 1}"
    return f"{now.year - 1}/{now.year}"


def _arabize(value):
    if value is None:
        return ""
    text = str(value)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    except Exception:
        return text


def _build_filters(user_id, trim, args, moy_expr_override=None):
    niveau = args.get("niveau", "")
    search = (args.get("recherche") or "").strip()
    sort = args.get("sort", "class")
    order = args.get("order", "asc")
    etat = args.get("etat", "all")
    min_moy = _parse_float(args.get("min_moy", ""))
    max_moy = _parse_float(args.get("max_moy", ""))
    if min_moy is not None and max_moy is not None and min_moy > max_moy:
        min_moy, max_moy = max_moy, min_moy

    if order not in ("asc", "desc"):
        order = "asc"

    moy_expr = (
        moy_expr_override
        if moy_expr_override
        else f"((devoir_t{trim} + activite_t{trim})/2.0 + (compo_t{trim}*2.0))/3.0"
    )
    where = "e.user_id = ?"
    params = [user_id]

    if niveau and niveau != "all":
        where += " AND e.niveau = ?"
        params.append(niveau)
    if search:
        where += " AND e.nom_complet LIKE ?"
        params.append(f"%{search}%")

    if min_moy is not None:
        where += f" AND {moy_expr} >= ?"
        params.append(min_moy)
    if max_moy is not None:
        where += f" AND {moy_expr} <= ?"
        params.append(max_moy)

    if etat == "admis":
        where += f" AND {moy_expr} >= 10"
    elif etat == "echec":
        where += f" AND {moy_expr} > 0 AND {moy_expr} < 10"
    elif etat == "non_saisi":
        where += f" AND {moy_expr} <= 0"

    return {
        "niveau": niveau,
        "search": search,
        "sort": sort,
        "order": order,
        "etat": etat,
        "min_moy": min_moy,
        "max_moy": max_moy,
        "moy_expr": moy_expr,
        "where": where,
        "params": params,
    }


def _build_history_filters(user_id, args):
    action = (args.get("action") or "").strip()
    q = (args.get("q") or "").strip()
    subject_val = (args.get("subject") or "").strip()
    date_from_raw = (args.get("from") or "").strip()
    date_to_raw = (args.get("to") or "").strip()

    subject_id = None
    try:
        if subject_val:
            subject_id = int(subject_val)
    except Exception:
        subject_id = None

    date_from = _parse_date(date_from_raw)
    date_to = _parse_date(date_to_raw)

    where = "l.user_id = ?"
    params = [user_id]

    if action:
        where += " AND l.action = ?"
        params.append(action)
    if subject_id:
        where += " AND l.subject_id = ?"
        params.append(subject_id)
    if q:
        where += " AND (l.details LIKE ? OR e.nom_complet LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    if date_from:
        where += " AND l.created_at >= ?"
        params.append(int(date_from.timestamp()))
    if date_to:
        end = date_to.replace(hour=23, minute=59, second=59)
        where += " AND l.created_at <= ?"
        params.append(int(end.timestamp()))

    return {
        "where": where,
        "params": params,
        "action": action,
        "q": q,
        "subject_id": subject_id,
        "date_from": date_from_raw,
        "date_to": date_to_raw,
    }


def _get_subjects(db, user_id):
    default_subject = ""
    lock_subject = 0
    try:
        user = db.execute(
            "SELECT default_subject, lock_subject FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        default_subject = (user["default_subject"] or "").strip() if user else ""
        lock_subject = int(user["lock_subject"] or 0) if user else 0
    except Exception:
        pass

    rows = db.execute(
        "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name",
        (user_id,),
    ).fetchall()
    if not rows:
        db.execute(
            "INSERT INTO subjects (user_id, name) VALUES (?, ?)",
            (user_id, default_subject or "Sciences"),
        )
        db.commit()
        rows = db.execute(
            "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name",
            (user_id,),
        ).fetchall()

    if lock_subject and default_subject:
        match = None
        for r in rows:
            if (r["name"] or "").strip().lower() == default_subject.lower():
                match = r
                break
        if not match:
            db.execute(
                "INSERT OR IGNORE INTO subjects (user_id, name) VALUES (?, ?)",
                (user_id, default_subject),
            )
            db.commit()
            rows = db.execute(
                "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name",
                (user_id,),
            ).fetchall()
            for r in rows:
                if (r["name"] or "").strip().lower() == default_subject.lower():
                    match = r
                    break
        if match:
            rows = [match]
    return rows


def _select_subject_id(subjects, value):
    subject_map = {int(s["id"]): s for s in subjects}
    try:
        sid = int(value)
    except Exception:
        sid = None
    if sid not in subject_map:
        sid = int(subjects[0]["id"])
    return sid


def _note_expr(trim):
    devoir = f"COALESCE(n.devoir, e.devoir_t{trim})"
    activite = f"COALESCE(n.activite, e.activite_t{trim})"
    compo = f"COALESCE(n.compo, e.compo_t{trim})"
    remarques = f"COALESCE(n.remarques, e.remarques_t{trim})"
    moy_expr = f"(({devoir} + {activite})/2.0 + ({compo}*2.0))/3.0"
    return devoir, activite, compo, remarques, moy_expr


@bp.route("/sauvegarder_tout", methods=["POST"])
@login_required
def sauvegarder_tout():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_save")
    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.form.get("subject"))

    ids = request.form.getlist("id_eleve")
    devs = request.form.getlist("devoir")
    acts = request.form.getlist("activite")
    comps = request.form.getlist("compo")

    updated = 0
    for i in range(len(ids)):
        try:
            d, a, c = clean_note(devs[i]), clean_note(acts[i]), clean_note(comps[i])
            moy = ((d + a) / 2 + (c * 2)) / 3
            rem = get_appreciation_dynamique(moy, user_id)
            db.execute(
                """
                INSERT INTO notes (user_id, eleve_id, subject_id, trimestre, activite, devoir, compo, remarques)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, eleve_id, subject_id, trimestre)
                DO UPDATE SET activite=excluded.activite, devoir=excluded.devoir, compo=excluded.compo, remarques=excluded.remarques
                """,
                (user_id, ids[i], subject_id, int(trim), a, d, c, rem),
            )
            updated += 1
        except Exception:
            continue
    db.commit()
    log_change("update_notes", user_id, details=f"{updated} lignes", subject_id=subject_id)
    flash("Notes enregistrees.", "success")
    return redirect(request.referrer or url_for("main.index", trimestre=trim))


@bp.route("/ajouter_eleve", methods=["POST"])
@login_required
def ajouter_eleve():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_ajout", "1")
    d = clean_note(request.form.get("devoir"))
    a = clean_note(request.form.get("activite"))
    c = clean_note(request.form.get("compo"))
    moy = ((d + a) / 2 + (c * 2)) / 3

    parent_phone = (request.form.get("parent_phone") or "").strip()
    parent_email = (request.form.get("parent_email") or "").strip()

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.form.get("subject"))

    cur = db.execute(
        f"INSERT INTO eleves (user_id, nom_complet, niveau, remarques_t{trim}, devoir_t{trim}, activite_t{trim}, compo_t{trim}, parent_phone, parent_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            request.form["nom_complet"],
            request.form["niveau"],
            get_appreciation_dynamique(moy, user_id),
            d,
            a,
            c,
            parent_phone,
            parent_email,
        ),
    )
    eleve_id = cur.lastrowid

    db.execute(
        """
        INSERT INTO notes (user_id, eleve_id, subject_id, trimestre, activite, devoir, compo, remarques)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, eleve_id, subject_id, trimestre)
        DO UPDATE SET activite=excluded.activite, devoir=excluded.devoir, compo=excluded.compo, remarques=excluded.remarques
        """,
        (user_id, eleve_id, subject_id, int(trim), a, d, c, get_appreciation_dynamique(moy, user_id)),
    )

    db.commit()
    log_change("add_student", user_id, details=request.form.get("nom_complet", ""), eleve_id=eleve_id, subject_id=subject_id)
    return redirect(request.referrer or url_for("main.index", trimestre=trim))


@bp.route("/supprimer_multi", methods=["POST"])
@login_required
def supprimer_multi():
    ids = request.form.getlist("ids")
    if ids:
        db = get_db()
        db.execute(
            f"DELETE FROM notes WHERE eleve_id IN ({','.join('?'*len(ids))}) AND user_id = ?",
            ids + [session["user_id"]],
        )
        db.execute(
            f"DELETE FROM eleves WHERE id IN ({','.join('?'*len(ids))}) AND user_id = ?",
            ids + [session["user_id"]],
        )
        db.commit()
        log_change("delete_students", session["user_id"], details=f"{len(ids)} eleves")
        flash(f"Supprimes ({len(ids)})", "success")
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/import_excel", methods=["POST"])
@login_required
def import_excel():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_import", "1")
    file = request.files.get("fichier_excel")
    if file and file.filename:
        try:
            db = get_db()
            subjects = _get_subjects(db, user_id)
            subject_id = _select_subject_id(subjects, request.form.get("subject"))

            all_sheets = pd.read_excel(file, sheet_name=None, header=None)
            inserted = 0
            updated = 0
            skipped = 0

            for nom_onglet, df in all_sheets.items():
                if df is None or df.empty:
                    continue

                header_row = -1
                for i, row in df.head(30).iterrows():
                    joined = " ".join([str(v) for v in row.values])
                    cells = [_normalize_header(v) for v in row.values]
                    if (
                        "Ã˜Â§Ã™â€žÃ™â€žÃ™â€šÃ˜Â¨" in joined
                        or "Nom" in joined
                        or "Ø§Ù„Ù„Ù‚Ø¨" in joined
                        or "Ø§Ù„Ø§Ø³Ù…" in joined
                        or any(
                            c in {"nom", "prenom", "nomcomplet", "nomprenom", "fullname"}
                            for c in cells
                        )
                    ):
                        header_row = i
                        break

                if header_row == -1:
                    skipped += 1
                    continue

                df.columns = df.iloc[header_row]
                df = df.iloc[header_row + 1 :]

                c_full = None
                c_nom = None
                c_prenom = None
                c_niveau = None
                c_d = None
                c_a = None
                c_c = None
                c_rem = None
                c_phone = None
                c_email = None

                for col in df.columns:
                    raw = str(col).strip()
                    norm = _normalize_header(col)

                    if norm in ("nomcomplet", "nomprenom", "fullname"):
                        c_full = col
                    elif norm in ("nom", "lastname", "surname"):
                        c_nom = col
                    elif norm in ("prenom", "firstname"):
                        c_prenom = col
                    elif norm in ("classe", "niveau", "class"):
                        c_niveau = col
                    elif norm in ("devoir", "dev", "homework", "04", "4"):
                        c_d = col
                    elif norm in ("activite", "activite", "act", "activity", "01", "1"):
                        c_a = col
                    elif norm in ("compo", "composition", "exam", "test", "09", "9"):
                        c_c = col
                    elif norm in ("remarques", "appreciation", "rem", "obs", "commentaire"):
                        c_rem = col
                    elif norm in ("telephone", "tel", "phone", "mobile"):
                        c_phone = col
                    elif norm in ("email", "mail", "e-mail"):
                        c_email = col
                    elif "Ø§Ù„Ù„Ù‚Ø¨" in raw:
                        c_nom = c_nom or col
                    elif "Ø§Ù„Ø§Ø³Ù…" in raw:
                        c_prenom = c_prenom or col
                    elif "Ø§Ù„Ù‚Ø³Ù…" in raw or "Ø§Ù„Ù…Ø³ØªÙˆÙ‰" in raw:
                        c_niveau = c_niveau or col
                    elif "Ø§Ù„ÙØ±Ø¶" in raw:
                        c_d = c_d or col
                    elif "Ø§Ù„Ù†Ø´Ø§Ø·" in raw:
                        c_a = c_a or col
                    elif "Ø§Ù„Ø§Ø®ØªØ¨Ø§Ø±" in raw:
                        c_c = c_c or col
                    elif "Ø§Ù„ØªÙ‚Ø¯ÙŠØ±" in raw:
                        c_rem = c_rem or col
                    elif "Ù‡Ø§ØªÙ" in raw or "Ø¬ÙˆØ§Ù„" in raw:
                        c_phone = c_phone or col
                    elif "Ø¨Ø±ÙŠØ¯" in raw:
                        c_email = c_email or col
                    elif "Ã˜Â§Ã™â€žÃ™â€žÃ™â€šÃ˜Â¨" in raw or "Nom" in raw:
                        c_nom = c_nom or col
                    elif "PrÃƒÂ©nom" in raw or "Prenom" in raw:
                        c_prenom = c_prenom or col
                    elif "Dev" in raw:
                        c_d = c_d or col
                    elif "Act" in raw:
                        c_a = c_a or col
                    elif "Compo" in raw:
                        c_c = c_c or col

                for _, row in df.iterrows():
                    def _val(c):
                        if c is None:
                            return None
                        v = row.get(c, None)
                        return None if pd.isna(v) else v

                    full = ""
                    if c_full:
                        full = str(_val(c_full) or "").strip()
                    else:
                        nom = str(_val(c_nom) or "").strip()
                        prenom = str(_val(c_prenom) or "").strip()
                        full = f"{nom} {prenom}".strip()

                    if not full:
                        continue

                    niveau = str(_val(c_niveau) or "").strip() if c_niveau else ""
                    if not niveau:
                        niveau = str(nom_onglet).strip() or "Global"

                    phone = str(_val(c_phone) or "").strip() if c_phone else ""
                    email = str(_val(c_email) or "").strip() if c_email else ""

                    d = clean_note(_val(c_d)) if c_d else 0
                    a = clean_note(_val(c_a)) if c_a else 0
                    c = clean_note(_val(c_c)) if c_c else 0
                    moy = ((d + a) / 2 + (c * 2)) / 3
                    rem = get_appreciation_dynamique(moy, user_id)
                    if c_rem:
                        custom_rem = _val(c_rem)
                        if custom_rem is not None and str(custom_rem).strip():
                            rem = str(custom_rem).strip()

                    ex = db.execute(
                        "SELECT id FROM eleves WHERE nom_complet = ? AND niveau = ? AND user_id = ?",
                        (full, niveau, user_id),
                    ).fetchone()

                    if ex:
                        db.execute(
                            "UPDATE eleves SET parent_phone = COALESCE(?, parent_phone), parent_email = COALESCE(?, parent_email) WHERE id = ?",
                            (phone or None, email or None, ex["id"]),
                        )
                        db.execute(
                            """
                            INSERT INTO notes (user_id, eleve_id, subject_id, trimestre, activite, devoir, compo, remarques)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(user_id, eleve_id, subject_id, trimestre)
                            DO UPDATE SET activite=excluded.activite, devoir=excluded.devoir, compo=excluded.compo, remarques=excluded.remarques
                            """,
                            (user_id, ex["id"], subject_id, int(trim), a, d, c, rem),
                        )
                        updated += 1
                    else:
                        cur = db.execute(
                            f"INSERT INTO eleves (user_id, nom_complet, niveau, remarques_t{trim}, devoir_t{trim}, activite_t{trim}, compo_t{trim}, parent_phone, parent_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (user_id, full, niveau, rem, d, a, c, phone, email),
                        )
                        eleve_id = cur.lastrowid
                        db.execute(
                            """
                            INSERT INTO notes (user_id, eleve_id, subject_id, trimestre, activite, devoir, compo, remarques)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(user_id, eleve_id, subject_id, trimestre)
                            DO UPDATE SET activite=excluded.activite, devoir=excluded.devoir, compo=excluded.compo, remarques=excluded.remarques
                            """,
                            (user_id, eleve_id, subject_id, int(trim), a, d, c, rem),
                        )
                        inserted += 1

            db.commit()
            total = inserted + updated
            log_change("import_excel", user_id, details=f"{total} lignes (new {inserted}, upd {updated}, skip {skipped})", subject_id=subject_id)
            flash(
                f"Import OK: {total} lignes (nouveaux {inserted}, mis a jour {updated}, onglets ignores {skipped})",
                "success",
            )
        except Exception as e:
            flash(f"Erreur: {e}", "danger")
    return redirect(request.referrer or url_for("main.index", trimestre=trim))


@bp.route("/remplir_bulletin_officiel", methods=["POST"])
@login_required
def remplir_bulletin_officiel():
    user_id = session["user_id"]
    trim = request.form.get("trimestre_fill", "1")
    file = request.files.get("fichier_vide")
    if file and file.filename:
        try:
            wb = openpyxl.load_workbook(file)
            db = get_db()
            for sheet in wb.worksheets:
                header_row = None
                col_map = {}
                for i, row in enumerate(
                    sheet.iter_rows(min_row=1, max_row=20, values_only=True)
                ):
                    row_str = [str(c).lower() for c in row if c]
                    if any(x in row_str for x in ["nom", "اللقب"]):
                        header_row = i + 1
                        for cell in sheet[header_row]:
                            if not cell.value:
                                continue
                            v = str(cell.value).strip().lower()
                            if v in ["nom", "اللقب"]:
                                col_map["nom"] = cell.column
                            elif v in ["prenom", "الاسم"]:
                                col_map["prenom"] = cell.column
                            elif v in ["01", "act", "النشاطات"]:
                                col_map["act"] = cell.column
                            elif v in ["04", "dev", "الفرض"]:
                                col_map["dev"] = cell.column
                            elif v in ["09", "compo", "الاختبار"]:
                                col_map["compo"] = cell.column
                            elif v in ["obs", "rem", "التقديرات"]:
                                col_map["rem"] = cell.column
                        break

                if header_row and "nom" in col_map:
                    for r in range(header_row + 1, sheet.max_row + 1):
                        nom = sheet.cell(row=r, column=col_map["nom"]).value
                        if not nom:
                            continue
                        prenom = (
                            sheet.cell(row=r, column=col_map.get("prenom")).value
                            if col_map.get("prenom")
                            else ""
                        )
                        full = f"{nom} {prenom}".strip()
                        el = db.execute(
                            "SELECT * FROM eleves WHERE nom_complet = ? AND user_id = ?",
                            (full, user_id),
                        ).fetchone()
                        if el:
                            if "act" in col_map:
                                sheet.cell(row=r, column=col_map["act"]).value = el[
                                    f"activite_t{trim}"
                                ]
                            if "dev" in col_map:
                                sheet.cell(row=r, column=col_map["dev"]).value = el[
                                    f"devoir_t{trim}"
                                ]
                            if "compo" in col_map:
                                sheet.cell(row=r, column=col_map["compo"]).value = el[
                                    f"compo_t{trim}"
                                ]
                            if "rem" in col_map:
                                sheet.cell(row=r, column=col_map["rem"]).value = el[
                                    f"remarques_t{trim}"
                                ]
            out = BytesIO()
            wb.save(out)
            out.seek(0)
            return send_file(
                out,
                download_name="Bulletin_Rempli.xlsx",
                as_attachment=True,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception as e:
            flash(f"Erreur: {e}", "danger")
    return redirect(request.referrer or url_for("main.index"))


@bp.route("/")
@login_required
def index():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = _note_expr(trim)
    filters = _build_filters(user_id, trim, request.args, moy_expr)
    niveau = filters["niveau"]
    search = filters["search"]
    sort = filters["sort"]
    order = filters["order"]
    etat = filters["etat"]
    min_moy = filters["min_moy"]
    max_moy = filters["max_moy"]

    try:
        page = int(request.args.get("page", "1") or 1)
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", "50") or 50)
    except ValueError:
        per_page = 50

    page = max(1, page)
    per_page = min(200, max(10, per_page))

    classes = [
        r["niveau"]
        for r in db.execute(
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? ORDER BY niveau",
            (user_id,),
        ).fetchall()
    ]

    where = filters["where"]
    params = filters["params"]

    join_params = [subject_id, int(trim)]

    stats_row = db.execute(
        f"""
        SELECT
          COUNT(*) AS nb_total,
          SUM(CASE WHEN {moy_expr} > 0 THEN 1 ELSE 0 END) AS nb_saisis,
          SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS nb_admis,
          AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS moyenne_generale,
          MAX(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS meilleure_note,
          MIN(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS pire_note
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        """,
        join_params + params,
    ).fetchone()

    total = int(stats_row["nb_total"] or 0)
    pages = max(1, (total + per_page - 1) // per_page)
    if page > pages:
        page = pages
    offset = (page - 1) * per_page

    direction = "DESC" if order == "desc" else "ASC"
    if sort == "name":
        order_clause = f"e.nom_complet COLLATE NOCASE {direction}, e.id ASC"
    elif sort == "moy":
        order_clause = f"moyenne {direction}, e.nom_complet COLLATE NOCASE ASC, e.id ASC"
    elif sort == "id":
        order_clause = f"e.id {direction}"
    else:
        order_clause = f"e.niveau COLLATE NOCASE {direction}, e.id ASC"

    rows = db.execute(
        f"""
        SELECT
          e.id,
          e.nom_complet,
          e.niveau,
          {devoir_expr} AS devoir,
          {activite_expr} AS activite,
          {compo_expr} AS compo,
          {remarques_expr} AS remarques,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        ORDER BY {order_clause}
        LIMIT ? OFFSET ?
        """,
        join_params + params + [per_page, offset],
    ).fetchall()

    eleves_list = [
        {
            "id": r["id"],
            "nom_complet": r["nom_complet"],
            "niveau": r["niveau"],
            "remarques": r["remarques"],
            "devoir": r["devoir"],
            "activite": r["activite"],
            "compo": r["compo"],
            "moyenne": float(r["moyenne"] or 0),
        }
        for r in rows
    ]

    nb_admis = int(stats_row["nb_admis"] or 0)
    nb_total = total

    stats = {
        "moyenne_generale": round(float(stats_row["moyenne_generale"] or 0), 2),
        "meilleure_note": round(float(stats_row["meilleure_note"] or 0), 2),
        "pire_note": round(float(stats_row["pire_note"] or 0), 2),
        "nb_admis": nb_admis,
        "taux_reussite": round((nb_admis / nb_total) * 100, 1) if nb_total else 0,
        "nb_total": nb_total,
        "nb_saisis": int(stats_row["nb_saisis"] or 0),
    }

    class_rows = db.execute(
        f"""
        SELECT
          e.niveau,
          COUNT(*) AS total,
          AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS avg_moy
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        GROUP BY e.niveau
        ORDER BY avg_moy DESC, e.niveau ASC
        """,
        join_params + params,
    ).fetchall()

    class_labels = [str(r["niveau"]) for r in class_rows]
    class_avgs = [round(float(r["avg_moy"] or 0), 2) for r in class_rows]

    dist_row = db.execute(
        f"""
        SELECT
          SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS admis,
          SUM(CASE WHEN {moy_expr} > 0 AND {moy_expr} < 10 THEN 1 ELSE 0 END) AS echec,
          SUM(CASE WHEN {moy_expr} <= 0 THEN 1 ELSE 0 END) AS non_saisi
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        """,
        join_params + params,
    ).fetchone()

    dist_values = [
        int(dist_row["admis"] or 0),
        int(dist_row["echec"] or 0),
        int(dist_row["non_saisi"] or 0),
    ]

    top_rows = db.execute(
        f"""
        SELECT
          e.nom_complet,
          e.niveau,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        ORDER BY moyenne DESC, e.nom_complet ASC
        LIMIT 10
        """,
        join_params + params,
    ).fetchall()

    top_eleves = [
        {"nom": r["nom_complet"], "niveau": r["niveau"], "moyenne": float(r["moyenne"] or 0)}
        for r in top_rows
    ]

    chart_data = json.dumps(
        {
            "classes": {"labels": class_labels, "values": class_avgs},
            "distribution": {"labels": ["Admis", "Echec", "Non saisi"], "values": dist_values},
        }
    )

    base_args = dict(request.args)
    base_args.pop("page", None)

    return render_template(
        "index.html",
        eleves=eleves_list,
        stats=stats,
        trimestre=trim,
        nom_prof=session.get("nom_affichage"),
        niveau_actuel=niveau,
        recherche_actuelle=search,
        liste_classes=classes,
        sort=sort,
        order=order,
        page=page,
        pages=pages,
        per_page=per_page,
        total=total,
        base_args=base_args,
        min_moy=min_moy,
        max_moy=max_moy,
        etat=etat,
        chart_data=chart_data,
        top_eleves=top_eleves,
        subjects=subjects,
        subject_id=subject_id,
        subject_name=subject_name,
        school_year=_school_year(datetime.now()),
        school_name=session.get("school_name"),
    )


@bp.route("/bulletin/<int:id>")
@login_required
def bulletin(id: int):
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = _note_expr(trim)

    eleve = db.execute(
        f"""
        SELECT
          e.*,
          {devoir_expr} AS devoir,
          {activite_expr} AS activite,
          {compo_expr} AS compo,
          {remarques_expr} AS remarques,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE e.id = ? AND e.user_id = ?
        """,
        (subject_id, int(trim), id, user_id),
    ).fetchone()
    if not eleve:
        return "Eleve introuvable"

    camarades = db.execute(
        f"""
        SELECT e.id, ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE e.user_id = ? AND e.niveau = ?
        """,
        (subject_id, int(trim), user_id, eleve["niveau"]),
    ).fetchall()

    scores = [(c["id"], float(c["moyenne"] or 0)) for c in camarades]
    scores.sort(key=lambda x: x[1], reverse=True)

    rank = next((i + 1 for i, s in enumerate(scores) if s[0] == id), 1)
    moy_eleve = float(eleve["moyenne"] or 0)
    moy_classe = sum(s[1] for s in scores) / len(scores) if scores else 0

    return render_template(
        "bulletin.html",
        eleve=eleve,
        rank=rank,
        total_eleves=len(scores),
        moyenne=round(moy_eleve, 2),
        moyenne_classe=round(moy_classe, 2),
        trimestre=trim,
        nom_prof=session.get("nom_affichage"),
        subject_name=subject_name,
        subject_id=subject_id,
    )


@bp.route("/bulletin_pdf/<int:id>")
@login_required
def bulletin_pdf(id: int):
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        flash("PDF indisponible. Installez reportlab (pip install reportlab).", "danger")
        return redirect(url_for("main.bulletin", id=id, trimestre=trim))

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = _note_expr(trim)

    eleve = db.execute(
        f"""
        SELECT
          e.*,
          {devoir_expr} AS devoir,
          {activite_expr} AS activite,
          {compo_expr} AS compo,
          {remarques_expr} AS remarques,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE e.id = ? AND e.user_id = ?
        """,
        (subject_id, int(trim), id, user_id),
    ).fetchone()
    if not eleve:
        return "Eleve introuvable"

    camarades = db.execute(
        f"""
        SELECT e.id, ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE e.user_id = ? AND e.niveau = ?
        """,
        (subject_id, int(trim), user_id, eleve["niveau"]),
    ).fetchall()

    scores = [(c["id"], float(c["moyenne"] or 0)) for c in camarades]
    scores.sort(key=lambda x: x[1], reverse=True)

    rank = next((i + 1 for i, s in enumerate(scores) if s[0] == id), 1)
    moy_eleve = float(eleve["moyenne"] or 0)
    moy_classe = sum(s[1] for s in scores) / len(scores) if scores else 0

    activite = eleve["activite"]
    devoir = eleve["devoir"]
    compo = eleve["compo"]
    moyenne = round(moy_eleve, 2)
    remarques = eleve["remarques"] or ""

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()

    story = []
    school_name = session.get("school_name") or os.environ.get("SCHOOL_NAME", "Etablissement")
    school_year = _school_year(datetime.now())
    logo_path = os.path.join(BASE_DIR, "static", "logo.png")
    stamp_path = os.path.join(BASE_DIR, "static", "stamp.png")

    header_right = Paragraph(
        f"<b>{school_name}</b><br/>Bulletin de notes<br/>Annee {school_year}",
        styles["Heading2"],
    )
    header_left = ""
    if os.path.exists(logo_path):
        from reportlab.platypus import Image

        header_left = Image(logo_path, width=28 * mm, height=28 * mm)

    header_table = Table([[header_left, header_right]], colWidths=[32 * mm, 150 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 6))

    info_data = [
        ["Eleve", eleve["nom_complet"]],
        ["Classe", eleve["niveau"]],
        ["Trimestre", trim],
        ["Matiere", subject_name],
        ["Prof", session.get("nom_affichage", "")],
    ]
    info_table = Table(info_data, colWidths=[28 * mm, 120 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, colors.black),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(info_table)
    story.append(Spacer(1, 10))

    table_data = [
        ["Matiere", "Activite", "Devoir", "Compo", "Moyenne", "Remarques"],
        [subject_name, activite, devoir, compo, moyenne, remarques],
    ]
    table = Table(
        table_data,
        colWidths=[35 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 51 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("ALIGN", (1, 1), (4, 1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 14))

    summary_data = [
        ["Moyenne classe", round(moy_classe, 2)],
        ["Rang", f"{rank} / {len(scores)}"],
        ["Moyenne eleve", moyenne],
    ]
    summary = Table(summary_data, colWidths=[60 * mm, 40 * mm])
    summary.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ]
        )
    )
    story.append(summary)
    story.append(Spacer(1, 12))
    story.append(Paragraph("Cachet et signature", styles["Normal"]))
    if os.path.exists(stamp_path):
        from reportlab.platypus import Image

        stamp = Image(stamp_path, width=28 * mm, height=28 * mm)
        stamp.hAlign = "RIGHT"
        story.append(stamp)

    doc.build(story)
    buffer.seek(0)

    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", eleve["nom_complet"])
    filename = f"bulletin_{safe_name}_T{trim}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@bp.route("/print_list")
@login_required
def print_list():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = _note_expr(trim)
    filters = _build_filters(user_id, trim, request.args, moy_expr)
    niveau = filters["niveau"]

    where = filters["where"]
    params = filters["params"]

    rows = db.execute(
        f"""
        SELECT
          e.nom_complet,
          e.niveau,
          {activite_expr} AS activite,
          {devoir_expr} AS devoir,
          {compo_expr} AS compo,
          ROUND({moy_expr}, 2) AS moyenne,
          {remarques_expr} AS remarques
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        ORDER BY e.niveau, e.id
        """,
        [subject_id, int(trim)] + params,
    ).fetchall()

    eleves_list = [
        {
            "nom_complet": r["nom_complet"],
            "niveau": r["niveau"],
            "activite": r["activite"],
            "devoir": r["devoir"],
            "compo": r["compo"],
            "moyenne": float(r["moyenne"] or 0),
            "remarques": r["remarques"],
        }
        for r in rows
    ]

    return render_template(
        "print_template.html",
        eleves=eleves_list,
        nom_prof=session.get("nom_affichage"),
        trimestre=trim,
        niveau=niveau,
        subject_name=subject_name,
    )


@bp.route("/export_list_pdf")
@login_required
def export_list_pdf():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        flash("PDF indisponible. Installez reportlab (pip install reportlab).", "danger")
        return redirect(request.referrer or url_for("main.index", trimestre=trim))

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = _note_expr(trim)
    filters = _build_filters(user_id, trim, request.args, moy_expr)

    where = filters["where"]
    params = filters["params"]

    rows = db.execute(
        f"""
        SELECT
          e.nom_complet,
          e.niveau,
          {activite_expr} AS activite,
          {devoir_expr} AS devoir,
          {compo_expr} AS compo,
          ROUND({moy_expr}, 2) AS moyenne,
          {remarques_expr} AS remarques
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        ORDER BY e.niveau, e.id
        """,
        [subject_id, int(trim)] + params,
    ).fetchall()

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font_name = "Helvetica"
    font_path = os.path.join(BASE_DIR, "static", "fonts", "Amiri-Regular.ttf")
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont("Arabic", font_path))
            font_name = "Arabic"
        except Exception:
            font_name = "Helvetica"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()

    story = []
    school_name = session.get("school_name") or os.environ.get("SCHOOL_NAME", "")
    class_label = filters.get("niveau") if "filters" in locals() else ""
    class_suffix = f" - {class_label}" if class_label and class_label != "all" else ""
    title = _arabize(f"\u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u062a\u0644\u0627\u0645\u064a\u0630{class_suffix} - T{trim} - {subject_name}")
    title_style = styles["Title"].clone("ArabicTitle")
    title_style.fontName = font_name
    title_style.alignment = 1
    if school_name:
        school_style = styles["Normal"].clone("ArabicSchool")
        school_style.fontName = font_name
        school_style.alignment = 1
        story.append(Paragraph(_arabize(school_name), school_style))
        story.append(Spacer(1, 4))
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 6))

    table_data = [[
        _arabize("\u0627\u0644\u0631\u0642\u0645"),
        _arabize("\u0627\u0644\u0627\u0633\u0645 \u0648 \u0627\u0644\u0644\u0642\u0628"),
        _arabize("\u0627\u0644\u0642\u0633\u0645"),
        _arabize("\u0627\u0644\u0646\u0634\u0627\u0637"),
        _arabize("\u0627\u0644\u0641\u0631\u0636"),
        _arabize("\u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631"),
        _arabize("\u0627\u0644\u0645\u0639\u062f\u0644"),
        _arabize("\u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a"),
    ]]
    for i, r in enumerate(rows, 1):
        table_data.append(
            [
                i,
                _arabize(r["nom_complet"]),
                _arabize(r["niveau"]),
                r["activite"],
                r["devoir"],
                r["compo"],
                r["moyenne"],
                _arabize(r["remarques"] or ""),
            ]
        )

    # RTL: invert column order so first column is on the right
    table_data = [list(reversed(row)) for row in table_data]
    col_widths = [10 * mm, 55 * mm, 26 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 80 * mm]
    col_widths = list(reversed(col_widths))

    table = Table(
        table_data,
        repeatRows=1,
        colWidths=col_widths,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("ALIGN", (0, 1), (0, -1), "RIGHT"),
                ("ALIGN", (1, 1), (1, -1), "CENTER"),
                ("ALIGN", (2, 1), (2, -1), "CENTER"),
                ("ALIGN", (3, 1), (3, -1), "CENTER"),
                ("ALIGN", (4, 1), (4, -1), "CENTER"),
                ("ALIGN", (5, 1), (5, -1), "CENTER"),
                ("ALIGN", (6, 1), (6, -1), "RIGHT"),
                ("ALIGN", (7, 1), (7, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(table)

    doc.build(story)
    buffer.seek(0)

    safe_subject = re.sub(r"[^A-Za-z0-9_-]+", "_", subject_name)
    filename = f"liste_eleves_T{trim}_{safe_subject}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


@bp.route("/export_excel")
@login_required
def export_excel():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.args.get("subject"))

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = _note_expr(trim)
    filters = _build_filters(user_id, trim, request.args, moy_expr)
    where = filters["where"]
    params = filters["params"]
    sort = filters["sort"]
    order = filters["order"]

    direction = "DESC" if order == "desc" else "ASC"
    if sort == "name":
        order_clause = f"e.nom_complet COLLATE NOCASE {direction}, e.id ASC"
    elif sort == "moy":
        order_clause = f"moyenne {direction}, e.nom_complet COLLATE NOCASE ASC, e.id ASC"
    elif sort == "id":
        order_clause = f"e.id {direction}"
    else:
        order_clause = f"e.niveau COLLATE NOCASE {direction}, e.id ASC"

    rows = db.execute(
        f"""
        SELECT
          e.id,
          e.nom_complet,
          e.niveau,
          {devoir_expr} AS devoir,
          {activite_expr} AS activite,
          {compo_expr} AS compo,
          {remarques_expr} AS remarques,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        ORDER BY {order_clause}
        """,
        [subject_id, int(trim)] + params,
    ).fetchall()

    data = []
    for r in rows:
        moy = float(r["moyenne"] or 0)
        if moy >= 10:
            etat = "Admis"
        elif moy > 0:
            etat = "Echec"
        else:
            etat = "Non saisi"
        data.append(
            {
                "ID": r["id"],
                "Nom complet": r["nom_complet"],
                "Classe": r["niveau"],
                "Activite": r["activite"],
                "Devoir": r["devoir"],
                "Compo": r["compo"],
                "Moyenne": moy,
                "Etat": etat,
                "Remarques": r["remarques"],
            }
        )

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=f"T{trim}")
    output.seek(0)

    filename = f"export_eleves_T{trim}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/export_parents")
@login_required
def export_parents():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    db = get_db()
    subjects = _get_subjects(db, user_id)
    subject_id = _select_subject_id(subjects, request.args.get("subject"))

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = _note_expr(trim)
    filters = _build_filters(user_id, trim, request.args, moy_expr)
    where = filters["where"]
    params = filters["params"]

    rows = db.execute(
        f"""
        SELECT
          e.nom_complet,
          e.niveau,
          e.parent_phone,
          e.parent_email,
          ROUND({moy_expr}, 2) AS moyenne,
          {remarques_expr} AS remarques
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        ORDER BY e.niveau, e.nom_complet
        """,
        [subject_id, int(trim)] + params,
    ).fetchall()

    data = []
    for r in rows:
        moy = float(r["moyenne"] or 0)
        if moy >= 10:
            etat = "Admis"
        elif moy > 0:
            etat = "Echec"
        else:
            etat = "Non saisi"
        data.append(
            {
                "Eleve": r["nom_complet"],
                "Classe": r["niveau"],
                "Tel parent": r["parent_phone"] or "",
                "Email parent": r["parent_email"] or "",
                "Moyenne": moy,
                "Etat": etat,
                "Remarques": r["remarques"],
                "Message": "",
            }
        )

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=f"Parents_T{trim}")
    output.seek(0)

    filename = f"export_parents_T{trim}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user_id = session["user_id"]
    db = get_db()

    if request.method == "POST":
        mins = request.form.getlist("min_val")
        maxs = request.form.getlist("max_val")
        msgs = request.form.getlist("message")

        db.execute("DELETE FROM appreciations WHERE user_id = ?", (user_id,))
        for i in range(len(mins)):
            if not mins[i]:
                continue
            try:
                min_v = float(mins[i])
                max_v = float(maxs[i]) if maxs[i] else min_v
            except ValueError:
                continue
            db.execute(
                "INSERT INTO appreciations (user_id, min_val, max_val, message) VALUES (?, ?, ?, ?)",
                (user_id, min_v, max_v, msgs[i]),
            )
        db.commit()

        # Recalcul rapide des remarques (notes)
        notes = db.execute(
            "SELECT id, activite, devoir, compo FROM notes WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        for n in notes:
            moy = ((n["devoir"] + n["activite"]) / 2 + (n["compo"] * 2)) / 3
            db.execute(
                "UPDATE notes SET remarques = ? WHERE id = ?",
                (get_appreciation_dynamique(moy, user_id), n["id"]),
            )

        # Legacy recalcul (old columns)
        for el in db.execute(
            "SELECT * FROM eleves WHERE user_id = ?",
            (user_id,),
        ).fetchall():
            for t in range(1, 4):
                moy = ((el[f"devoir_t{t}"] + el[f"activite_t{t}"]) / 2 + (el[f"compo_t{t}"] * 2)) / 3
                db.execute(
                    f"UPDATE eleves SET remarques_t{t} = ? WHERE id = ?",
                    (get_appreciation_dynamique(moy, user_id), el["id"]),
                )
        db.commit()
        flash("Sauvegarde", "success")

    rules = db.execute(
        "SELECT * FROM appreciations WHERE user_id = ? ORDER BY min_val",
        (user_id,),
    ).fetchall()
    return render_template("settings.html", rules=rules)


@bp.route("/timetable", methods=["GET", "POST"])
@login_required
def timetable():
    user_id = session["user_id"]
    db = get_db()

    classes = [
        r["niveau"]
        for r in db.execute(
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? ORDER BY niveau",
            (user_id,),
        ).fetchall()
    ]

    niveau = request.values.get("niveau", "")
    days = [
        {"key": "mon", "label": "Lundi"},
        {"key": "tue", "label": "Mardi"},
        {"key": "wed", "label": "Mercredi"},
        {"key": "thu", "label": "Jeudi"},
        {"key": "fri", "label": "Vendredi"},
        {"key": "sat", "label": "Samedi"},
    ]
    slots = [
        {"key": "s1", "label": "08:00-09:00"},
        {"key": "s2", "label": "09:00-10:00"},
        {"key": "s3", "label": "10:00-11:00"},
        {"key": "s4", "label": "11:00-12:00"},
        {"key": "s5", "label": "13:00-14:00"},
        {"key": "s6", "label": "14:00-15:00"},
    ]

    if request.method == "POST" and niveau:
        updated = 0
        for d in days:
            for s in slots:
                key = f"cell_{d['key']}_{s['key']}"
                value = (request.form.get(key) or "").strip()
                if value:
                    db.execute(
                        """
                        INSERT INTO timetable (user_id, niveau, day, slot, label)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, niveau, day, slot)
                        DO UPDATE SET label=excluded.label
                        """,
                        (user_id, niveau, d["key"], s["key"], value),
                    )
                    updated += 1
                else:
                    db.execute(
                        "DELETE FROM timetable WHERE user_id = ? AND niveau = ? AND day = ? AND slot = ?",
                        (user_id, niveau, d["key"], s["key"]),
                    )
        db.commit()
        log_change("update_timetable", user_id, details=f"{niveau} ({updated} cases)")
        flash("Emploi du temps enregistre.", "success")
        return redirect(url_for("main.timetable", niveau=niveau))

    grid = {}
    if niveau:
        rows = db.execute(
            "SELECT day, slot, label FROM timetable WHERE user_id = ? AND niveau = ?",
            (user_id, niveau),
        ).fetchall()
        for r in rows:
            grid.setdefault(r["day"], {})[r["slot"]] = r["label"]

    return render_template(
        "timetable.html",
        liste_classes=classes,
        niveau_actuel=niveau,
        days=days,
        slots=slots,
        grid=grid,
    )


@bp.route("/subjects", methods=["GET", "POST"])
@login_required
def subjects():
    user_id = session["user_id"]
    db = get_db()
    if not session.get("is_admin"):
        try:
            row = db.execute(
                "SELECT lock_subject FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row and int(row["lock_subject"] or 0) == 1:
                flash("Acces reserve a l'administration.", "warning")
                return redirect(url_for("main.index"))
        except Exception:
            pass
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Nom manquant", "danger")
        else:
            try:
                db.execute(
                    "INSERT INTO subjects (user_id, name) VALUES (?, ?)",
                    (user_id, name),
                )
                db.commit()
                log_change("add_subject", user_id, details=name)
                flash("Matiere ajoutee", "success")
            except Exception:
                flash("Matiere existe deja", "warning")

    subjects_list = db.execute(
        "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name",
        (user_id,),
    ).fetchall()
    return render_template("subjects.html", subjects=subjects_list)


@bp.route("/subjects/delete/<int:subject_id>", methods=["POST"])
@login_required
def delete_subject(subject_id: int):
    user_id = session["user_id"]
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) as c FROM subjects WHERE user_id = ?",
        (user_id,),
    ).fetchone()["c"]
    if count <= 1:
        flash("Impossible de supprimer la derniere matiere", "warning")
        return redirect(url_for("main.subjects"))

    db.execute(
        "DELETE FROM notes WHERE user_id = ? AND subject_id = ?",
        (user_id, subject_id),
    )
    db.execute(
        "DELETE FROM subjects WHERE user_id = ? AND id = ?",
        (user_id, subject_id),
    )
    db.commit()
    log_change("delete_subject", user_id, details=str(subject_id), subject_id=subject_id)
    flash("Matiere supprimee", "success")
    return redirect(url_for("main.subjects"))


@bp.route("/history")
@login_required
def history():
    user_id = session["user_id"]
    db = get_db()
    actions = [
        r["action"]
        for r in db.execute(
            "SELECT DISTINCT action FROM change_log WHERE user_id = ? ORDER BY action",
            (user_id,),
        ).fetchall()
    ]
    subjects = _get_subjects(db, user_id)

    filters = _build_history_filters(user_id, request.args)
    where = filters["where"]
    params = filters["params"]

    rows = db.execute(
        f"""
        SELECT l.*, e.nom_complet AS eleve_name, s.name AS subject_name
        FROM change_log l
        LEFT JOIN eleves e ON e.id = l.eleve_id
        LEFT JOIN subjects s ON s.id = l.subject_id
        WHERE {where}
        ORDER BY l.created_at DESC
        LIMIT 200
        """,
        params,
    ).fetchall()

    logs = []
    for r in rows:
        item = dict(r)
        try:
            item["time"] = datetime.fromtimestamp(item["created_at"]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            item["time"] = str(item.get("created_at", ""))
        logs.append(item)

    export_url = url_for("main.history_export", **dict(request.args))
    return render_template(
        "history.html",
        logs=logs,
        actions=actions,
        subjects=subjects,
        filters=filters,
        export_url=export_url,
        total=len(logs),
    )


@bp.route("/history/export")
@login_required
def history_export():
    user_id = session["user_id"]
    db = get_db()

    filters = _build_history_filters(user_id, request.args)
    where = filters["where"]
    params = filters["params"]

    rows = db.execute(
        f"""
        SELECT l.*, e.nom_complet AS eleve_name, s.name AS subject_name
        FROM change_log l
        LEFT JOIN eleves e ON e.id = l.eleve_id
        LEFT JOIN subjects s ON s.id = l.subject_id
        WHERE {where}
        ORDER BY l.created_at DESC
        """,
        params,
    ).fetchall()

    output = BytesIO()
    wrapper = TextIOWrapper(output, encoding="utf-8", newline="")
    writer = csv.writer(wrapper)
    writer.writerow(["Date", "Action", "Eleve", "Matiere", "Details"])
    for r in rows:
        try:
            date_val = datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_val = str(r.get("created_at", ""))
        writer.writerow(
            [
                date_val,
                r["action"],
                r["eleve_name"] or "",
                r["subject_name"] or "",
                r["details"] or "",
            ]
        )
    wrapper.flush()
    output.seek(0)

    filename = f"historique_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="text/csv")


