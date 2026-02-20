import os
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, send_file

from core.config import BASE_DIR
from core.db import get_db
from core.security import login_required
from edumaster.services.common import (
    arabize,
    get_subjects,
    get_user_assignment_scope,
    parse_trim,
    resolve_school_year,
    select_subject_id,
)
from edumaster.services.filters import build_filters
from edumaster.services.grading import note_expr
from edumaster.services.reports import build_bulletin_multisubject

bp = Blueprint("reports", __name__)

@bp.route("/bulletin/<int:id>")
@login_required
def bulletin(id: int):
    user_id = session["user_id"]
    trim = parse_trim(request.args.get("trimestre", "1"))

    db = get_db()
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    data = build_bulletin_multisubject(db, user_id, id, trim, selected_school_year)
    if not data:
        return "Eleve introuvable"

    return render_template(
        "bulletin.html",
        eleve=data["eleve"],
        subject_lines=data["subject_lines"],
        rank=data["rank"],
        total_eleves=data["total_eleves"],
        moyenne_generale=data["moyenne_generale"],
        moyenne_classe=data["moyenne_classe"],
        trimestre=trim,
        school_year=selected_school_year,
        nom_prof=session.get("nom_affichage"),
    )


@bp.route("/bulletin_pdf/<int:id>")
@login_required
def bulletin_pdf(id: int):
    user_id = session["user_id"]
    trim = parse_trim(request.args.get("trimestre", "1"))

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        flash("PDF indisponible. Installez reportlab (pip install reportlab).", "danger")
        return redirect(
            url_for(
                "reports.bulletin",
                id=id,
                trimestre=trim,
                school_year=request.args.get("school_year", ""),
            )
        )

    db = get_db()
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    data = build_bulletin_multisubject(db, user_id, id, trim, selected_school_year)
    if not data:
        return "Eleve introuvable"
    eleve = data["eleve"]
    subject_lines = data["subject_lines"]
    moyenne_generale = data["moyenne_generale"]
    moyenne_classe = data["moyenne_classe"]
    rank = data["rank"]
    total_eleves = data["total_eleves"]

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
    s_year = selected_school_year
    logo_path = os.path.join(BASE_DIR, "static", "logo.png")
    stamp_path = os.path.join(BASE_DIR, "static", "stamp.png")

    header_right = Paragraph(
        f"<b>{school_name}</b><br/>Bulletin de notes<br/>Annee {s_year}",
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
        ["Nombre matieres", len(subject_lines)],
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
    ]
    for line in subject_lines:
        table_data.append(
            [
                line["subject_name"],
                line["activite"],
                line["devoir"],
                line["compo"],
                line["moyenne"],
                line["remarques"],
            ]
        )

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
        ["Moyenne classe", moyenne_classe],
        ["Rang", f"{rank} / {total_eleves}"],
        ["Moyenne generale", moyenne_generale],
    ]
    summary = Table(summary_data, colWidths=[60 * mm, 40 * mm])
    summary.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
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
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    scope = (
        {"restricted": False, "subject_ids": set(), "classes": set()}
        if session.get("is_admin")
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    if scope["restricted"] and subject_id not in scope["subject_ids"]:
        allowed_subjects = [s for s in subjects if int(s["id"]) in scope["subject_ids"]]
        if allowed_subjects:
            subject_id = int(allowed_subjects[0]["id"])
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(
        user_id,
        trim,
        request.args,
        selected_school_year,
        moy_expr,
        allowed_classes=(scope["classes"] if scope["restricted"] else None),
    )
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
        school_year=selected_school_year,
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
        return redirect(
            request.referrer
            or url_for(
                "dashboard.index",
                trimestre=trim,
                school_year=request.args.get("school_year", ""),
            )
        )

    db = get_db()
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    scope = (
        {"restricted": False, "subject_ids": set(), "classes": set()}
        if session.get("is_admin")
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    if scope["restricted"] and subject_id not in scope["subject_ids"]:
        allowed_subjects = [s for s in subjects if int(s["id"]) in scope["subject_ids"]]
        if allowed_subjects:
            subject_id = int(allowed_subjects[0]["id"])
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(
        user_id,
        trim,
        request.args,
        selected_school_year,
        moy_expr,
        allowed_classes=(scope["classes"] if scope["restricted"] else None),
    )

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
    font_bold = "Helvetica-Bold"
    font_path = os.path.join(BASE_DIR, "static", "fonts", "TimesNewRoman-Regular.ttf")
    font_bold_path = os.path.join(BASE_DIR, "static", "fonts", "TimesNewRoman-Bold.ttf")
    if os.path.exists(font_path) and os.path.exists(font_bold_path):
        try:
            pdfmetrics.registerFont(TTFont("Arabic", font_path))
            pdfmetrics.registerFont(TTFont("ArabicBold", font_bold_path))
            font_name = "Arabic"
            font_bold = "ArabicBold"
        except Exception:
            font_name = "Helvetica"
            font_bold = "Helvetica-Bold"

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
    title = arabize(f"\u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u062a\u0644\u0627\u0645\u064a\u0630{class_suffix} - {selected_school_year} - T{trim} - {subject_name}")
    title_style = styles["Title"].clone("ArabicTitle")
    title_style.fontName = font_bold
    title_style.alignment = 1
    if school_name:
        school_style = styles["Normal"].clone("ArabicSchool")
        school_style.fontName = font_bold
        school_style.alignment = 1
        story.append(Paragraph(arabize(school_name), school_style))
        story.append(Spacer(1, 4))
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 6))

    prof_name = session.get("nom_affichage")
    if prof_name:
        prof_style = styles["Normal"].clone("ArabicProf")
        prof_style.fontName = font_name
        prof_style.alignment = 1
        story.append(
            Paragraph(arabize(f"\u0627\u0644\u0623\u0633\u062a\u0627\u0630: {prof_name}"), prof_style)
        )
        story.append(Spacer(1, 6))

    table_data = [[
        arabize("\u0627\u0644\u0631\u0642\u0645"),
        arabize("\u0627\u0644\u0627\u0633\u0645 \u0648 \u0627\u0644\u0644\u0642\u0628"),
        arabize("\u0627\u0644\u0642\u0633\u0645"),
        arabize("\u0627\u0644\u0646\u0634\u0627\u0637"),
        arabize("\u0627\u0644\u0641\u0631\u0636"),
        arabize("\u0627\u0644\u0627\u062e\u062a\u0628\u0627\u0631"),
        arabize("\u0627\u0644\u0645\u0639\u062f\u0644"),
        arabize("\u0627\u0644\u0645\u0644\u0627\u062d\u0638\u0627\u062a"),
    ]]
    for i, r in enumerate(rows, 1):
        table_data.append(
            [
                i,
                arabize(r["nom_complet"]),
                arabize(r["niveau"]),
                r["activite"],
                r["devoir"],
                r["compo"],
                r["moyenne"],
                arabize(r["remarques"] or ""),
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
                ("FONTNAME", (0, 0), (-1, 0), font_bold),
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
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    scope = (
        {"restricted": False, "subject_ids": set(), "classes": set()}
        if session.get("is_admin")
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    if scope["restricted"] and subject_id not in scope["subject_ids"]:
        allowed_subjects = [s for s in subjects if int(s["id"]) in scope["subject_ids"]]
        if allowed_subjects:
            subject_id = int(allowed_subjects[0]["id"])

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(
        user_id,
        trim,
        request.args,
        selected_school_year,
        moy_expr,
        allowed_classes=(scope["classes"] if scope["restricted"] else None),
    )
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
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    scope = (
        {"restricted": False, "subject_ids": set(), "classes": set()}
        if session.get("is_admin")
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    if scope["restricted"] and subject_id not in scope["subject_ids"]:
        allowed_subjects = [s for s in subjects if int(s["id"]) in scope["subject_ids"]]
        if allowed_subjects:
            subject_id = int(allowed_subjects[0]["id"])

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(
        user_id,
        trim,
        request.args,
        selected_school_year,
        moy_expr,
        allowed_classes=(scope["classes"] if scope["restricted"] else None),
    )
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

@bp.route("/export_stats_pdf")
@login_required
def export_stats_pdf():
    import os
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    
    user_id = session["user_id"]
    db = get_db()
    
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"
        
    selected_school_year = resolve_school_year(db, request.args.get("school_year"), is_admin=bool(session.get("is_admin")))
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    
    is_admin = bool(session.get("is_admin"))
    assignment_scope = {"restricted": False, "subject_ids": set(), "classes": set()} if is_admin else get_user_assignment_scope(db, user_id, selected_school_year)
    
    if assignment_scope["restricted"] and subject_id not in assignment_scope["subject_ids"]:
        allowed_subjects = [s for s in subjects if int(s["id"]) in assignment_scope["subject_ids"]]
        if allowed_subjects:
            subject_id = int(allowed_subjects[0]["id"])
            
    if not subjects:
        flash("Ajoutez d'abord une matiere.", "warning")
        return redirect(url_for("dashboard.subjects"))
        
    subject_name = next((s["name"] for s in subjects if int(s["id"]) == subject_id), "Matière inconnue")
    school_name = session.get("school_name", "Établissement")
    nom_prof = session.get("nom_affichage", "")
    
    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(user_id, trim, request.args, selected_school_year, moy_expr, allowed_classes=(assignment_scope["classes"] if assignment_scope["restricted"] else None))
    niveau = filters["niveau"]
    search = filters["search"]
    where = filters["where"]
    params = filters["params"]
    join_params = [subject_id, int(trim)]

    # Fetch stats exactly like in dashboard.stats
    stats_row = db.execute(
        f"SELECT COUNT(*) AS nb_total, SUM(CASE WHEN {moy_expr} > 0 THEN 1 ELSE 0 END) AS nb_saisis, SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS nb_admis, AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS moyenne_generale, MAX(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS meilleure_note, MIN(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS pire_note FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where}",
        join_params + params,
    ).fetchone()

    total = int(stats_row["nb_total"] or 0)
    nb_admis = int(stats_row["nb_admis"] or 0)
    moyenne_generale = round(float(stats_row["moyenne_generale"] or 0), 2)
    meilleure_note = round(float(stats_row["meilleure_note"] or 0), 2)
    pire_note = round(float(stats_row["pire_note"] or 0), 2)
    taux_reussite = round((nb_admis / total) * 100, 1) if total else 0

    class_rows = db.execute(
        f"SELECT e.niveau, COUNT(*) AS total, AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS avg_moy FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where} GROUP BY e.niveau ORDER BY avg_moy DESC, e.niveau ASC",
        join_params + params,
    ).fetchall()

    dist_row = db.execute(
        f"SELECT SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS admis, SUM(CASE WHEN {moy_expr} > 0 AND {moy_expr} < 10 THEN 1 ELSE 0 END) AS echec, SUM(CASE WHEN {moy_expr} <= 0 THEN 1 ELSE 0 END) AS non_saisi FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where}",
        join_params + params,
    ).fetchone()

    top_rows = db.execute(
        f"SELECT e.nom_complet, e.niveau, ROUND({moy_expr}, 2) AS moyenne FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where} ORDER BY moyenne DESC, e.nom_complet ASC LIMIT 10",
        join_params + params,
    ).fetchall()
    
    risk_rows = db.execute(
        f"SELECT e.nom_complet, e.niveau, ROUND({moy_expr}, 2) AS moyenne FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where} AND {moy_expr} > 0 AND {moy_expr} < 10 ORDER BY moyenne ASC, e.nom_complet ASC LIMIT 10",
        join_params + params,
    ).fetchall()

    font_name = "Helvetica"
    font_bold = "Helvetica-Bold"
    font_path = os.path.join(BASE_DIR, "static", "fonts", "TimesNewRoman-Regular.ttf")
    font_bold_path = os.path.join(BASE_DIR, "static", "fonts", "TimesNewRoman-Bold.ttf")
    if os.path.exists(font_path) and os.path.exists(font_bold_path):
        try:
            pdfmetrics.registerFont(TTFont("Arabic", font_path))
            pdfmetrics.registerFont(TTFont("ArabicBold", font_bold_path))
            font_name = "Arabic"
            font_bold = "ArabicBold"
        except Exception:
            font_name = "Helvetica"
            font_bold = "Helvetica-Bold"

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()

    # Title
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName=font_bold, fontSize=18, spaceAfter=20, alignment=2)
    subtitle_style = ParagraphStyle('SubtitleStyle', parent=styles['Normal'], fontName=font_name, fontSize=12, spaceAfter=20, alignment=2)
    
    niveau_text = niveau if niveau and niveau != "all" else "جميع الأقسام"
    elements.append(Paragraph(arabize(f"التقرير الإحصائي - الثلاثي {trim}"), title_style))
    elements.append(Paragraph(arabize(f"{school_name} | {nom_prof} | {subject_name} | {niveau_text} | {selected_school_year}"), subtitle_style))

    # General Stats
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontName=font_bold, fontSize=14, spaceAfter=10, textColor=colors.darkblue, alignment=2)
    
    gen_data = [
        [arabize("أعلى / أدنى نقطة"), arabize("ناجح / المجموع"), arabize("نسبة النجاح"), arabize("المعدل العام")],
        [f"{pire_note} / {meilleure_note}", f"{total} / {nb_admis}", f"{taux_reussite}%", str(moyenne_generale)]
    ]
    t_gen = Table(gen_data, colWidths=[130, 130, 130, 130])
    t_gen.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), font_bold),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('TEXTCOLOR', (2,1), (2,1), colors.green),
    ]))
    elements.append(KeepTogether([
        Paragraph(arabize("الإحصائيات العامة"), h2_style),
        t_gen
    ]))
    elements.append(Spacer(1, 20))

    # Classes Stats
    class_data = [[arabize("المعدل"), arabize("العدد"), arabize("القسم")]]
    for r in class_rows:
        class_data.append([str(round(float(r["avg_moy"] or 0), 2)), str(r["total"]), arabize(str(r["niveau"]))])
    if len(class_data) > 1:
        t_class = Table(class_data, colWidths=[100, 100, 200])
        t_class.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), font_bold),
            ('FONTNAME', (2,1), (2,-1), font_name), # applied to student class name col
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(KeepTogether([
            Paragraph(arabize("المعدلات حسب القسم"), h2_style),
            t_class
        ]))
    else:
        elements.append(KeepTogether([
            Paragraph(arabize("المعدلات حسب القسم"), h2_style),
            Paragraph(arabize("لا توجد بيانات للأقسام."), styles['Normal'])
        ]))
    elements.append(Spacer(1, 20))

    # Distribution Note
    dist_data = [
        [arabize("غير مدخل"), arabize("راسب (< 10)"), arabize("ناجح (>= 10)")],
        [str(dist_row["non_saisi"] or 0), str(dist_row["echec"] or 0), str(dist_row["admis"] or 0)]
    ]
    t_dist = Table(dist_data, colWidths=[150, 150, 150])
    t_dist.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), font_bold),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('TEXTCOLOR', (2,1), (2,1), colors.green),
        ('TEXTCOLOR', (1,1), (1,1), colors.red),
    ]))
    elements.append(KeepTogether([
        Paragraph(arabize("توزيع النقاط"), h2_style),
        t_dist
    ]))
    elements.append(Spacer(1, 20))
    
    # Top Students
    top_data = [[arabize("المعدل"), arabize("القسم"), arabize("الاسم واللقب"), arabize("الرتبة")]]
    for i, r in enumerate(top_rows, 1):
        top_data.append([str(float(r["moyenne"])), arabize(r["niveau"]), arabize(r["nom_complet"]), str(i)])
    if len(top_data) > 1:
        t_top = Table(top_data, colWidths=[80, 100, 250, 50])
        t_top.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('ALIGN', (2,1), (2,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,0), font_bold),
            ('FONTNAME', (1,1), (2,-1), font_name), # Applied to student name and class column
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(KeepTogether([
            Paragraph(arabize("أفضل 10 تلاميذ"), h2_style),
            t_top
        ]))
    else:
        elements.append(KeepTogether([
            Paragraph(arabize("أفضل 10 تلاميذ"), h2_style),
            Paragraph(arabize("لم يتم العثور على أي تلميذ."), styles['Normal'])
        ]))
    elements.append(Spacer(1, 20))
    
    # Risk Students
    risk_data = [[arabize("المعدل"), arabize("القسم"), arabize("الاسم واللقب")]]
    for r in risk_rows:
        risk_data.append([str(float(r["moyenne"])), arabize(r["niveau"]), arabize(r["nom_complet"])])
    if len(risk_data) > 1:
        t_risk = Table(risk_data, colWidths=[80, 100, 250])
        t_risk.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('ALIGN', (2,1), (2,-1), 'RIGHT'),
            ('FONTNAME', (0,0), (-1,0), font_bold),
            ('FONTNAME', (1,1), (2,-1), font_name), # Applied to student name and class col
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('TEXTCOLOR', (0,1), (0,-1), colors.red),
        ]))
        elements.append(KeepTogether([
            Paragraph(arabize("تلاميذ في حالة ضعف (أقصى 10)"), h2_style),
            t_risk
        ]))
    else:
        elements.append(KeepTogether([
            Paragraph(arabize("تلاميذ في حالة ضعف (أقصى 10)"), h2_style),
            Paragraph(arabize("لا يوجد أي تلميذ في حالة تعثر."), styles['Normal'])
        ]))

    doc.build(elements)
    buffer.seek(0)
    
    filename = f"statistiques_T{trim}.pdf"
    
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
