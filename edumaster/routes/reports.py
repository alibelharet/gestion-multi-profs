import os
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, send_file

from core.config import BASE_DIR
from core.db import get_db
from core.security import login_required
from edumaster.services.common import school_year, get_subjects, select_subject_id, parse_trim, arabize
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
    data = build_bulletin_multisubject(db, user_id, id, trim)
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
        return redirect(url_for("reports.bulletin", id=id, trimestre=trim))

    db = get_db()
    data = build_bulletin_multisubject(db, user_id, id, trim)
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
    s_year = school_year(datetime.now())
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
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(user_id, trim, request.args, moy_expr)
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
        return redirect(request.referrer or url_for("dashboard.index", trimestre=trim))

    db = get_db()
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(user_id, trim, request.args, moy_expr)

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
    title = arabize(f"\u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u062a\u0644\u0627\u0645\u064a\u0630{class_suffix} - T{trim} - {subject_name}")
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
        story.append(Paragraph(arabize(f"Ø§Ù„Ø£Ø³ØªØ§Ø°: {prof_name}"), prof_style))
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
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(user_id, trim, request.args, moy_expr)
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
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(user_id, trim, request.args, moy_expr)
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
