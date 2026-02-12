import os
import uuid
import pandas as pd
import openpyxl
from io import BytesIO
from datetime import datetime
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, send_file

from core.audit import log_change
from core.db import get_db
from core.security import login_required, write_required
from core.utils import clean_note, get_appreciation_dynamique
from edumaster.services.common import get_subjects, select_subject_id, parse_trim
from edumaster.services.grading import clean_component, split_activite_components, sum_activite_components
from edumaster.services.import_utils import (
    preview_dir, cleanup_import_previews, get_preview_meta, clear_preview_meta,
    prepare_import_dataframe, build_default_mapping, resolve_mapped_column, row_value
)

bp = Blueprint("imports", __name__)

IMPORT_MAPPING_FIELDS = [
    ("full_name", "Nom complet"),
    ("last_name", "Nom"),
    ("first_name", "Prenom"),
    ("classe", "Classe"),
    ("devoir", "Devoir (/20)"),
    ("activite", "Activite (/20)"),
    ("compo", "Compo (/20)"),
    ("participation", "Participation (/3)"),
    ("comportement", "Comportement (/6)"),
    ("cahier", "Cahier (/5)"),
    ("projet", "Projet (/4)"),
    ("assiduite_outils", "Absences/Outils (/2)"),
    ("remarques", "Remarques"),
    ("phone", "Telephone parent"),
    ("email", "Email parent"),
]

@bp.route("/import_excel", methods=["POST"])
@login_required
@write_required
def import_excel():
    user_id = session["user_id"]
    trim = parse_trim(request.form.get("trimestre_import", "1"))
    file = request.files.get("fichier_excel")
    if not file or not file.filename:
        flash("Fichier Excel manquant.", "warning")
        return redirect(request.referrer or url_for("dashboard.index", trimestre=trim))

    db = get_db()
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.form.get("subject"))
    previous_meta = session.get("import_preview")
    if isinstance(previous_meta, dict):
        clear_preview_meta(previous_meta)
    cleanup_import_previews()

    token = uuid.uuid4().hex
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".xlsx", ".xls", ".xlsm"):
        ext = ".xlsx"
    preview_path = os.path.join(preview_dir(), f"{token}{ext}")

    try:
        file.save(preview_path)
        all_sheets = pd.read_excel(preview_path, sheet_name=None, header=None)
    except Exception as exc:
        try:
            if os.path.exists(preview_path):
                os.remove(preview_path)
        except Exception:
            pass
        flash(f"Erreur lecture Excel: {exc}", "danger")
        return redirect(request.referrer or url_for("dashboard.index", trimestre=trim))

    selected_sheet = ""
    selected_df = None
    header_detected = False
    for sheet_name, raw_df in (all_sheets or {}).items():
        prepared, _, detected = prepare_import_dataframe(raw_df)
        if prepared is None or prepared.empty:
            continue
        selected_sheet = str(sheet_name)
        selected_df = prepared
        header_detected = detected
        break

    if selected_df is None or selected_df.empty:
        try:
            if os.path.exists(preview_path):
                os.remove(preview_path)
        except Exception:
            pass
        flash("Aucune ligne exploitable detectee dans le fichier.", "warning")
        return redirect(request.referrer or url_for("dashboard.index", trimestre=trim))

    columns = [str(c) for c in selected_df.columns]
    defaults = build_default_mapping(columns)
    sample_df = selected_df.head(8).copy()
    sample_rows = []
    for _, row in sample_df.iterrows():
        current = {}
        for col in columns:
            value = row.get(col, "")
            if pd.isna(value):
                value = ""
            current[col] = str(value).strip()
        sample_rows.append(current)

    session["import_preview"] = {
        "token": token,
        "path": preview_path,
        "trim": trim,
        "subject_id": int(subject_id),
        "sheet_name": selected_sheet,
        "created_at": int(datetime.now().timestamp()),
    }

    if not header_detected:
        flash("Entete non detectee automatiquement: verifiez bien la correspondance des colonnes.", "warning")

    return render_template(
        "import_mapping.html",
        token=token,
        mapping_fields=IMPORT_MAPPING_FIELDS,
        columns=columns,
        defaults=defaults,
        sample_rows=sample_rows,
        sample_headers=columns,
        source_sheet=selected_sheet,
        trim=trim,
        subject_id=subject_id,
    )


@bp.route("/import_excel_apply", methods=["POST"])
@login_required
@write_required
def import_excel_apply():
    user_id = session["user_id"]
    token = (request.form.get("token") or "").strip()
    meta = get_preview_meta(token)
    if not meta:
        flash("Session d'import expiree. Recommencez l'import.", "warning")
        return redirect(url_for("dashboard.index"))

    trim = parse_trim(meta.get("trim"), "1")
    db = get_db()
    subjects = get_subjects(db, user_id)
    subject_ids = {int(s["id"]) for s in subjects}
    try:
        subject_id = int(meta.get("subject_id"))
    except Exception:
        subject_id = None
    if subject_id not in subject_ids:
        subject_id = select_subject_id(subjects, request.form.get("subject"))

    mapping = {}
    for key, _label in IMPORT_MAPPING_FIELDS:
        mapping[key] = (request.form.get(f"map_{key}") or "").strip()

    try:
        all_sheets = pd.read_excel(meta["path"], sheet_name=None, header=None)
    except Exception as exc:
        clear_preview_meta(meta)
        flash(f"Lecture impossible pendant validation: {exc}", "danger")
        return redirect(url_for("dashboard.index", trimestre=trim, subject=subject_id))

    inserted = 0
    updated = 0
    skipped_sheets = 0
    skipped_rows = 0
    use_components = any(
        mapping.get(k)
        for k in ("participation", "comportement", "cahier", "projet", "assiduite_outils")
    )

    for sheet_name, raw_df in (all_sheets or {}).items():
        prepared, _, _ = prepare_import_dataframe(raw_df)
        if prepared is None or prepared.empty:
            skipped_sheets += 1
            continue

        columns = list(prepared.columns)
        resolved = {k: resolve_mapped_column(columns, v) for k, v in mapping.items()}
        if not resolved.get("full_name") and not (
            resolved.get("last_name") or resolved.get("first_name")
        ):
            skipped_sheets += 1
            continue

        for _, row in prepared.iterrows():
            try:
                if resolved.get("full_name"):
                    full = str(row_value(row, resolved["full_name"]) or "").strip()
                else:
                    last_name = str(row_value(row, resolved.get("last_name")) or "").strip()
                    first_name = str(row_value(row, resolved.get("first_name")) or "").strip()
                    full = f"{last_name} {first_name}".strip()

                if not full:
                    skipped_rows += 1
                    continue

                niveau = str(row_value(row, resolved.get("classe")) or "").strip()
                if not niveau:
                    niveau = str(sheet_name).strip() or "Global"

                phone = str(row_value(row, resolved.get("phone")) or "").strip()
                email = str(row_value(row, resolved.get("email")) or "").strip()

                d = clean_note(row_value(row, resolved.get("devoir")))
                c = clean_note(row_value(row, resolved.get("compo")))

                if use_components:
                    p = clean_component(row_value(row, resolved.get("participation")), 3)
                    b = clean_component(row_value(row, resolved.get("comportement")), 6)
                    k = clean_component(row_value(row, resolved.get("cahier")), 5)
                    pr = clean_component(row_value(row, resolved.get("projet")), 4)
                    ao = clean_component(row_value(row, resolved.get("assiduite_outils")), 2)
                else:
                    p, b, k, pr, ao = split_activite_components(
                        row_value(row, resolved.get("activite"))
                    )
                a = sum_activite_components(p, b, k, pr, ao)

                moy = ((d + a) / 2 + (c * 2)) / 3
                rem = get_appreciation_dynamique(moy, user_id)
                custom_rem = row_value(row, resolved.get("remarques"))
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
                        INSERT INTO notes (
                            user_id, eleve_id, subject_id, trimestre,
                            participation, comportement, cahier, projet, assiduite_outils,
                            activite, devoir, compo, remarques
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, eleve_id, subject_id, trimestre)
                        DO UPDATE SET
                            participation=excluded.participation,
                            comportement=excluded.comportement,
                            cahier=excluded.cahier,
                            projet=excluded.projet,
                            assiduite_outils=excluded.assiduite_outils,
                            activite=excluded.activite,
                            devoir=excluded.devoir,
                            compo=excluded.compo,
                            remarques=excluded.remarques
                        """,
                        (user_id, ex["id"], subject_id, int(trim), p, b, k, pr, ao, a, d, c, rem),
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
                        INSERT INTO notes (
                            user_id, eleve_id, subject_id, trimestre,
                            participation, comportement, cahier, projet, assiduite_outils,
                            activite, devoir, compo, remarques
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, eleve_id, subject_id, trimestre)
                        DO UPDATE SET
                            participation=excluded.participation,
                            comportement=excluded.comportement,
                            cahier=excluded.cahier,
                            projet=excluded.projet,
                            assiduite_outils=excluded.assiduite_outils,
                            activite=excluded.activite,
                            devoir=excluded.devoir,
                            compo=excluded.compo,
                            remarques=excluded.remarques
                        """,
                        (user_id, eleve_id, subject_id, int(trim), p, b, k, pr, ao, a, d, c, rem),
                    )
                    inserted += 1
            except Exception:
                skipped_rows += 1
                continue

    db.commit()
    clear_preview_meta(meta)

    total = inserted + updated
    log_change(
        "import_excel",
        user_id,
        details=f"{total} lignes (new {inserted}, upd {updated}, sheets {skipped_sheets}, rows {skipped_rows})",
        subject_id=subject_id,
    )
    flash(
        f"Import termine: {total} lignes (nouveaux {inserted}, maj {updated}, onglets ignores {skipped_sheets}, lignes ignorees {skipped_rows})",
        "success",
    )
    return redirect(url_for("dashboard.index", trimestre=trim, subject=subject_id))


@bp.route("/import_excel_cancel/<token>")
@login_required
def import_excel_cancel(token: str):
    meta = get_preview_meta((token or "").strip())
    if meta:
        clear_preview_meta(meta)
    return redirect(url_for("dashboard.index"))

@bp.route("/remplir_bulletin_officiel", methods=["POST"])
@login_required
@write_required
def remplir_bulletin_officiel():
    user_id = session["user_id"]
    trim = parse_trim(request.form.get("trimestre_fill", "1"))
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
                    if any(x in row_str for x in ["nom", "Ø§Ù„Ù„Ù‚Ø¨"]):
                        header_row = i + 1
                        for cell in sheet[header_row]:
                            if not cell.value:
                                continue
                            v = str(cell.value).strip().lower()
                            if v in ["nom", "Ø§Ù„Ù„Ù‚Ø¨"]:
                                col_map["nom"] = cell.column
                            elif v in ["prenom", "Ø§Ù„Ø§Ø³Ù…"]:
                                col_map["prenom"] = cell.column
                            elif v in ["01", "act", "Ø§Ù„Ù†Ø´Ø§Ø·Ø§Øª"]:
                                col_map["act"] = cell.column
                            elif v in ["04", "dev", "Ø§Ù„Ù Ø±Ø¶"]:
                                col_map["dev"] = cell.column
                            elif v in ["09", "compo", "Ø§Ù„Ø§Ø®ØªØ¨Ø§Ø±"]:
                                col_map["compo"] = cell.column
                            elif v in ["obs", "rem", "Ø§Ù„ØªÙ‚Ø¯ÙŠØ±Ø§Øª"]:
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
    return redirect(request.referrer or url_for("dashboard.index"))
