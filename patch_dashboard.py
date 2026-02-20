import re

filepath = r"c:\Users\21379\OneDrive\Bureau\Gestion_Multi_Profs\edumaster\routes\dashboard.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the index function return statement to remove stats variables
old_index_return = """    return render_template(
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
        risk_students=risk_students,
        risk_count=risk_count,
        risk_url=risk_url,
        subjects=subjects,
        subject_id=subject_id,
        subject_name=subject_name,
        can_edit=can_edit,
        school_year=selected_school_year,
        school_years=list_school_years(db),
        active_school_year=get_active_school_year(db),
        school_name=session.get("school_name"),
    )"""

new_index_return = """    return render_template(
        "index.html",
        eleves=eleves_list,
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
        subjects=subjects,
        subject_id=subject_id,
        subject_name=subject_name,
        can_edit=can_edit,
        school_year=selected_school_year,
        school_years=list_school_years(db),
        active_school_year=get_active_school_year(db),
        school_name=session.get("school_name"),
    )"""
content = content.replace(old_index_return, new_index_return)

# Now redefine the stats function to include all the logic
old_stats_func = """@bp.route("/stats")
@login_required
def stats():
    user_id = session["user_id"]
    db = get_db()
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    if not session.get("is_admin"):
        scope = get_user_assignment_scope(db, user_id, selected_school_year)
        if scope["restricted"] and subject_id not in scope["subject_ids"]:
            allowed_subjects = [s for s in subjects if int(s["id"]) in scope["subject_ids"]]
            if allowed_subjects:
                subject_id = int(allowed_subjects[0]["id"])
    
    # Handle case where no subjects exist
    if not subjects:
        flash("Ajoutez d'abord une matiere.", "warning")
        return redirect(url_for("dashboard.subjects"))
        
    subject_name = next((s["name"] for s in subjects if int(s["id"]) == subject_id), "Matière inconnue")
    
    evolution = get_class_evolution(user_id, subject_id, selected_school_year)
    # Convert set to list for template if necessary, but it's a list already
    
    # Get top students
    top_students = get_best_students_evolution(user_id, subject_id, selected_school_year, limit=5)

    return render_template(
        "stats.html",
        subjects=subjects,
        subject_id=subject_id,
        subject_name=subject_name,
        school_year=selected_school_year,
        school_years=list_school_years(db),
        active_school_year=get_active_school_year(db),
        evolution=evolution,
        top_students=top_students
    )"""

new_stats_func = """@bp.route("/stats")
@login_required
def stats():
    user_id = session["user_id"]
    db = get_db()
    
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"
        
    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    
    is_admin = bool(session.get("is_admin"))
    assignment_scope = (
        {"restricted": False, "subject_ids": set(), "classes": set()}
        if is_admin
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )
    
    if assignment_scope["restricted"] and subject_id not in assignment_scope["subject_ids"]:
        allowed_subjects = [s for s in subjects if int(s["id"]) in assignment_scope["subject_ids"]]
        if allowed_subjects:
            subject_id = int(allowed_subjects[0]["id"])
    
    if not subjects:
        flash("Ajoutez d'abord une matiere.", "warning")
        return redirect(url_for("dashboard.subjects"))
        
    subject_name = next((s["name"] for s in subjects if int(s["id"]) == subject_id), "Matière inconnue")
    
    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(
        user_id,
        trim,
        request.args,
        selected_school_year,
        moy_expr,
        allowed_classes=(assignment_scope["classes"] if assignment_scope["restricted"] else None),
    )
    niveau = filters["niveau"]
    search = filters["search"]
    where = filters["where"]
    params = filters["params"]
    join_params = [subject_id, int(trim)]

    stats_row = db.execute(
        f"SELECT COUNT(*) AS nb_total, SUM(CASE WHEN {moy_expr} > 0 THEN 1 ELSE 0 END) AS nb_saisis, SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS nb_admis, AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS moyenne_generale, MAX(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS meilleure_note, MIN(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS pire_note FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where}",
        join_params + params,
    ).fetchone()

    total = int(stats_row["nb_total"] or 0)
    nb_admis = int(stats_row["nb_admis"] or 0)

    stats = {
        "moyenne_generale": round(float(stats_row["moyenne_generale"] or 0), 2),
        "meilleure_note": round(float(stats_row["meilleure_note"] or 0), 2),
        "pire_note": round(float(stats_row["pire_note"] or 0), 2),
        "nb_admis": nb_admis,
        "taux_reussite": round((nb_admis / total) * 100, 1) if total else 0,
        "nb_total": total,
        "nb_saisis": int(stats_row["nb_saisis"] or 0),
    }

    class_rows = db.execute(
        f"SELECT e.niveau, COUNT(*) AS total, AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS avg_moy FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where} GROUP BY e.niveau ORDER BY avg_moy DESC, e.niveau ASC",
        join_params + params,
    ).fetchall()
    class_labels = [str(r["niveau"]) for r in class_rows]
    class_avgs = [round(float(r["avg_moy"] or 0), 2) for r in class_rows]

    dist_row = db.execute(
        f"SELECT SUM(CASE WHEN {moy_expr} >= 10 THEN 1 ELSE 0 END) AS admis, SUM(CASE WHEN {moy_expr} > 0 AND {moy_expr} < 10 THEN 1 ELSE 0 END) AS echec, SUM(CASE WHEN {moy_expr} <= 0 THEN 1 ELSE 0 END) AS non_saisi FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where}",
        join_params + params,
    ).fetchone()

    dist_values = [
        int(dist_row["admis"] or 0),
        int(dist_row["echec"] or 0),
        int(dist_row["non_saisi"] or 0),
    ]

    top_rows = db.execute(
        f"SELECT e.nom_complet, e.niveau, ROUND({moy_expr}, 2) AS moyenne FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {where} ORDER BY moyenne DESC, e.nom_complet ASC LIMIT 10",
        join_params + params,
    ).fetchall()

    top_eleves = [{"nom": r["nom_complet"], "niveau": r["niveau"], "moyenne": float(r["moyenne"] or 0)} for r in top_rows]

    risk_where = "e.user_id = ? AND e.school_year = ?"
    risk_params = [user_id, selected_school_year]
    if niveau and niveau != "all":
        risk_where += " AND e.niveau = ?"
        risk_params.append(niveau)
    elif assignment_scope["restricted"] and assignment_scope["classes"]:
        placeholders = ",".join("?" for _ in sorted(assignment_scope["classes"]))
        risk_where += f" AND e.niveau IN ({placeholders})"
        risk_params.extend(sorted(assignment_scope["classes"]))
    if search:
        risk_where += " AND e.nom_complet LIKE ?"
        risk_params.append(f"%{search}%")

    risk_count_row = db.execute(
        f"SELECT COUNT(*) AS c FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {risk_where} AND {moy_expr} > 0 AND {moy_expr} < 10",
        join_params + risk_params,
    ).fetchone()
    risk_count = int(risk_count_row["c"] or 0)

    risk_rows = db.execute(
        f"SELECT e.id, e.nom_complet, e.niveau, ROUND({moy_expr}, 2) AS moyenne FROM eleves e LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ? WHERE {risk_where} AND {moy_expr} > 0 AND {moy_expr} < 10 ORDER BY moyenne ASC, e.nom_complet ASC LIMIT 8",
        join_params + risk_params,
    ).fetchall()
    
    risk_students = [{"id": int(r["id"]), "nom": r["nom_complet"], "niveau": r["niveau"], "moyenne": float(r["moyenne"] or 0)} for r in risk_rows]
    
    risk_args = dict(request.args)
    risk_args["etat"] = "echec"
    risk_args["school_year"] = selected_school_year
    risk_args.pop("page", None)
    risk_url = url_for("dashboard.index", **risk_args)

    chart_data = {
        "classes": {"labels": class_labels, "values": class_avgs},
        "distribution": {"labels": ["Admis", "Echec", "Non saisi"], "values": dist_values},
    }

    evolution = get_class_evolution(user_id, subject_id, selected_school_year)
    top_students_annual = get_best_students_evolution(user_id, subject_id, selected_school_year, limit=5)

    class_lists = db.execute(
        "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? AND school_year = ? ORDER BY niveau",
        (user_id, selected_school_year),
    ).fetchall()
    all_classes = [r["niveau"] for r in class_lists]

    return render_template(
        "stats.html",
        subjects=subjects,
        subject_id=subject_id,
        subject_name=subject_name,
        school_year=selected_school_year,
        school_years=list_school_years(db),
        active_school_year=get_active_school_year(db),
        stats=stats,
        top_eleves=top_eleves,
        risk_students=risk_students,
        risk_count=risk_count,
        risk_url=risk_url,
        chart_data=chart_data,
        evolution=evolution,
        top_students=top_students_annual,
        trimestre=trim,
        niveau_actuel=niveau,
        liste_classes=all_classes,
    )"""

content = content.replace(old_stats_func, new_stats_func)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print("Dashboard logic updated successfully!")
