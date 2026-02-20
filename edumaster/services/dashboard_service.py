"""Dashboard business logic extracted from routes/dashboard.py."""

from edumaster.services.grading import note_expr, split_activite_components


def compute_stats_summary(db, user_id, trim, subject_id, where, params):
    """Compute summary statistics (total, admis, moyenne, min, max) for students."""
    _, _, _, _, moy_expr = note_expr(trim)
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
    nb_admis = int(stats_row["nb_admis"] or 0)

    return {
        "moyenne_generale": round(float(stats_row["moyenne_generale"] or 0), 2),
        "meilleure_note": round(float(stats_row["meilleure_note"] or 0), 2),
        "pire_note": round(float(stats_row["pire_note"] or 0), 2),
        "nb_admis": nb_admis,
        "taux_reussite": round((nb_admis / total) * 100, 1) if total else 0,
        "nb_total": total,
        "nb_saisis": int(stats_row["nb_saisis"] or 0),
    }


def fetch_students_page(db, user_id, trim, subject_id, where, params,
                         sort, order, page, per_page):
    """Fetch a page of students with their grades and computed averages."""
    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    join_params = [subject_id, int(trim)]

    direction = "DESC" if order == "desc" else "ASC"
    sort_map = {
        "name": f"e.nom_complet COLLATE NOCASE {direction}, e.id ASC",
        "moy": f"moyenne {direction}, e.nom_complet COLLATE NOCASE ASC, e.id ASC",
        "id": f"e.id {direction}",
    }
    order_clause = sort_map.get(sort, f"e.niveau COLLATE NOCASE {direction}, e.id ASC")

    offset = (page - 1) * per_page
    rows = db.execute(
        f"""
        SELECT
          e.id,
          e.nom_complet,
          e.niveau,
          COALESCE(n.participation, 0) AS participation,
          COALESCE(n.comportement, 0) AS comportement,
          COALESCE(n.cahier, 0) AS cahier,
          COALESCE(n.projet, 0) AS projet,
          COALESCE(n.assiduite_outils, 0) AS assiduite_outils,
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

    eleves = []
    for r in rows:
        p = float(r["participation"] or 0)
        b = float(r["comportement"] or 0)
        k = float(r["cahier"] or 0)
        pr = float(r["projet"] or 0)
        ao = float(r["assiduite_outils"] or 0)
        activite_value = float(r["activite"] or 0)
        if activite_value > 0 and p == 0 and b == 0 and k == 0 and pr == 0 and ao == 0:
            p, b, k, pr, ao = split_activite_components(activite_value)

        eleves.append({
            "id": r["id"],
            "nom_complet": r["nom_complet"],
            "niveau": r["niveau"],
            "remarques": r["remarques"],
            "devoir": float(r["devoir"] or 0),
            "activite": activite_value,
            "compo": float(r["compo"] or 0),
            "participation": p,
            "comportement": b,
            "cahier": k,
            "projet": pr,
            "assiduite_outils": ao,
            "moyenne": float(r["moyenne"] or 0),
        })
    return eleves


def compute_chart_data(db, user_id, trim, subject_id, where, params,
                        niveau, search, assignment_scope, selected_school_year):
    """Compute chart data: class averages, distribution, progression, top/risk students."""
    _, _, _, _, moy_expr = note_expr(trim)
    join_params = [subject_id, int(trim)]

    # Class averages
    class_rows = db.execute(
        f"""
        SELECT e.niveau, COUNT(*) AS total,
          AVG(CASE WHEN {moy_expr} > 0 THEN {moy_expr} END) AS avg_moy
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where}
        GROUP BY e.niveau ORDER BY avg_moy DESC, e.niveau ASC
        """,
        join_params + params,
    ).fetchall()
    class_labels = [str(r["niveau"]) for r in class_rows]
    class_avgs = [round(float(r["avg_moy"] or 0), 2) for r in class_rows]

    # Distribution
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

    # Top students
    top_rows = db.execute(
        f"""
        SELECT e.nom_complet, e.niveau, ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {where} ORDER BY moyenne DESC, e.nom_complet ASC LIMIT 10
        """,
        join_params + params,
    ).fetchall()
    top_eleves = [
        {"nom": r["nom_complet"], "niveau": r["niveau"], "moyenne": float(r["moyenne"] or 0)}
        for r in top_rows
    ]

    # Risk students
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
        f"""
        SELECT COUNT(*) AS c FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {risk_where} AND {moy_expr} > 0 AND {moy_expr} < 10
        """,
        join_params + risk_params,
    ).fetchone()
    risk_count = int(risk_count_row["c"] or 0)

    risk_rows = db.execute(
        f"""
        SELECT e.id, e.nom_complet, e.niveau, ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {risk_where} AND {moy_expr} > 0 AND {moy_expr} < 10
        ORDER BY moyenne ASC, e.nom_complet ASC LIMIT 8
        """,
        join_params + risk_params,
    ).fetchall()
    risk_students = [
        {"id": int(r["id"]), "nom": r["nom_complet"], "niveau": r["niveau"], "moyenne": float(r["moyenne"] or 0)}
        for r in risk_rows
    ]

    # Progression across trimesters
    m1 = "((COALESCE(n1.devoir, e.devoir_t1) + COALESCE(n1.activite, e.activite_t1))/2.0 + (COALESCE(n1.compo, e.compo_t1) * 2.0))/3.0"
    m2 = "((COALESCE(n2.devoir, e.devoir_t2) + COALESCE(n2.activite, e.activite_t2))/2.0 + (COALESCE(n2.compo, e.compo_t2) * 2.0))/3.0"
    m3 = "((COALESCE(n3.devoir, e.devoir_t3) + COALESCE(n3.activite, e.activite_t3))/2.0 + (COALESCE(n3.compo, e.compo_t3) * 2.0))/3.0"

    progress_where = "e.user_id = ? AND e.school_year = ?"
    progress_params = [user_id, selected_school_year]
    if niveau and niveau != "all":
        progress_where += " AND e.niveau = ?"
        progress_params.append(niveau)
    elif assignment_scope["restricted"] and assignment_scope["classes"]:
        placeholders = ",".join("?" for _ in sorted(assignment_scope["classes"]))
        progress_where += f" AND e.niveau IN ({placeholders})"
        progress_params.extend(sorted(assignment_scope["classes"]))
    if search:
        progress_where += " AND e.nom_complet LIKE ?"
        progress_params.append(f"%{search}%")

    progress_rows = db.execute(
        f"""
        SELECT e.niveau,
          AVG(CASE WHEN {m1} > 0 THEN {m1} END) AS t1,
          AVG(CASE WHEN {m2} > 0 THEN {m2} END) AS t2,
          AVG(CASE WHEN {m3} > 0 THEN {m3} END) AS t3
        FROM eleves e
        LEFT JOIN notes n1 ON n1.user_id = e.user_id AND n1.eleve_id = e.id AND n1.subject_id = ? AND n1.trimestre = 1
        LEFT JOIN notes n2 ON n2.user_id = e.user_id AND n2.eleve_id = e.id AND n2.subject_id = ? AND n2.trimestre = 2
        LEFT JOIN notes n3 ON n3.user_id = e.user_id AND n3.eleve_id = e.id AND n3.subject_id = ? AND n3.trimestre = 3
        WHERE {progress_where}
        GROUP BY e.niveau ORDER BY e.niveau COLLATE NOCASE ASC
        """,
        [subject_id, subject_id, subject_id] + progress_params,
    ).fetchall()

    return {
        "classes": {"labels": class_labels, "values": class_avgs},
        "distribution": {"labels": ["Admis", "Echec", "Non saisi"], "values": dist_values},
        "progression": {
            "labels": [str(r["niveau"]) for r in progress_rows],
            "t1": [round(float(r["t1"] or 0), 2) for r in progress_rows],
            "t2": [round(float(r["t2"] or 0), 2) for r in progress_rows],
            "t3": [round(float(r["t3"] or 0), 2) for r in progress_rows],
        },
        "top_eleves": top_eleves,
        "risk_students": risk_students,
        "risk_count": risk_count,
    }
