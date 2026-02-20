import re

filepath = r"c:\Users\21379\OneDrive\Bureau\Gestion_Multi_Profs\edumaster\routes\reports.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Find the start of the export_stats_pdf route
start_idx = content.find('@bp.route("/export_stats_pdf")')
if start_idx != -1:
    content = content[:start_idx] # Keep everything before it

new_func = """@bp.route("/export_stats_pdf")
@login_required
def export_stats_pdf():
    import os
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
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
    title_style = ParagraphStyle('TitleStyle', parent=styles['Title'], fontName=font_bold, fontSize=18, spaceAfter=20, alignment=1)
    subtitle_style = ParagraphStyle('SubtitleStyle', parent=styles['Normal'], fontName=font_name, fontSize=12, spaceAfter=20, alignment=1)
    
    niveau_text = niveau if niveau and niveau != "all" else "Toutes les classes"
    elements.append(Paragraph(arabize(f"Rapport Statistique - Trimestre {trim}"), title_style))
    elements.append(Paragraph(arabize(f"{school_name} | {nom_prof} | {subject_name} | {niveau_text} | {selected_school_year}"), subtitle_style))

    # General Stats
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=14, spaceAfter=10, textColor=colors.darkblue)
    elements.append(Paragraph("Statistiques Générales", h2_style))
    
    gen_data = [
        ["Moyenne Générale", "Taux de Réussite", "Admis / Total", "Max / Min"],
        [str(moyenne_generale), f"{taux_reussite}%", f"{nb_admis} / {total}", f"{meilleure_note} / {pire_note}"]
    ]
    t_gen = Table(gen_data, colWidths=[130, 130, 130, 130])
    t_gen.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 11),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('TEXTCOLOR', (1,1), (1,1), colors.green),
    ]))
    elements.append(t_gen)
    elements.append(Spacer(1, 20))

    # Classes Stats
    elements.append(Paragraph("Moyennes par Classe", h2_style))
    class_data = [["Classe", "Effectif", "Moyenne"]]
    for r in class_rows:
        class_data.append([arabize(str(r["niveau"])), str(r["total"]), str(round(float(r["avg_moy"] or 0), 2))])
    if len(class_data) > 1:
        t_class = Table(class_data, colWidths=[200, 100, 100])
        t_class.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,1), (0,-1), font_name), # applied to student class name col
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(t_class)
    else:
        elements.append(Paragraph("Pas de données de classe.", styles['Normal']))
    elements.append(Spacer(1, 20))

    # Distribution Note
    elements.append(Paragraph("Répartition des Notes", h2_style))
    dist_data = [
        ["Admis (>= 10)", "Échec (< 10)", "Non saisi"],
        [str(dist_row["admis"] or 0), str(dist_row["echec"] or 0), str(dist_row["non_saisi"] or 0)]
    ]
    t_dist = Table(dist_data, colWidths=[150, 150, 150])
    t_dist.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('TEXTCOLOR', (0,1), (0,1), colors.green),
        ('TEXTCOLOR', (1,1), (1,1), colors.red),
    ]))
    elements.append(t_dist)
    elements.append(Spacer(1, 20))
    
    # Top Students
    elements.append(Paragraph("Top 10 Élèves", h2_style))
    top_data = [["Rang", "Nom et Prénom", "Classe", "Moyenne"]]
    for i, r in enumerate(top_rows, 1):
        top_data.append([str(i), arabize(r["nom_complet"]), arabize(r["niveau"]), str(float(r["moyenne"]))])
    if len(top_data) > 1:
        t_top = Table(top_data, colWidths=[50, 250, 100, 80])
        t_top.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('ALIGN', (1,1), (1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (1,1), (2,-1), font_name), # Applied to student name and class column
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(t_top)
    else:
        elements.append(Paragraph("Aucun élève trouvé.", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Risk Students
    elements.append(Paragraph(f"Élèves en Difficulté (Max 10)", h2_style))
    risk_data = [["Nom et Prénom", "Classe", "Moyenne"]]
    for r in risk_rows:
        risk_data.append([arabize(r["nom_complet"]), arabize(r["niveau"]), str(float(r["moyenne"]))])
    if len(risk_data) > 1:
        t_risk = Table(risk_data, colWidths=[250, 100, 80])
        t_risk.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('ALIGN', (0,1), (0,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,1), (1,-1), font_name), # Applied to student name and class col
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('TEXTCOLOR', (2,1), (2,-1), colors.red),
        ]))
        elements.append(t_risk)
    else:
        elements.append(Paragraph("Aucun élève en difficulté.", styles['Normal']))

    doc.build(elements)
    buffer.seek(0)
    
    filename = f"statistiques_T{trim}.pdf"
    
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
"""

content += new_func

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Arabic PDF generation updated.")
