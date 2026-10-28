from .grading import note_expr
from core.db import get_db


def get_declining_students(
    user_id,
    subject_id,
    school_year,
    current_trim,
    *,
    niveau=None,
    allowed_classes=None,
    search="",
    limit=8,
    min_drop=1.0,
):
    """Return students whose average dropped versus the previous trimester."""
    trim = str(current_trim)
    if trim not in ("2", "3"):
        return []

    previous_trim = str(int(trim) - 1)
    current_expr = note_expr(trim, 'nc')[4]
    previous_expr = note_expr(previous_trim, 'np')[4]

    where = ["e.user_id = ?", "e.school_year = ?"]
    params = [subject_id, int(trim), subject_id, int(previous_trim), user_id, school_year]

    if niveau and niveau != "all":
        where.append("e.niveau = ?")
        params.append(niveau)
    elif allowed_classes is not None:
        classes = sorted(set(allowed_classes))
        if not classes:
            return []
        placeholders = ",".join("?" for _ in classes)
        where.append(f"e.niveau IN ({placeholders})")
        params.extend(classes)

    if search:
        where.append("e.nom_complet LIKE ?")
        params.append(f"%{search}%")

    params.extend([float(min_drop), max(1, int(limit))])
    rows = get_db().execute(
        f"""
        SELECT
            e.id,
            e.nom_complet,
            e.niveau,
            ROUND({previous_expr}, 2) AS previous_average,
            ROUND({current_expr}, 2) AS current_average,
            ROUND({current_expr} - {previous_expr}, 2) AS delta
        FROM eleves e
        LEFT JOIN notes nc
            ON nc.user_id = e.user_id
            AND nc.eleve_id = e.id
            AND nc.subject_id = ?
            AND nc.trimestre = ?
        LEFT JOIN notes np
            ON np.user_id = e.user_id
            AND np.eleve_id = e.id
            AND np.subject_id = ?
            AND np.trimestre = ?
        WHERE {' AND '.join(where)}
            AND {previous_expr} IS NOT NULL
            AND {current_expr} IS NOT NULL
            AND ({previous_expr} - {current_expr}) >= ?
        ORDER BY delta ASC, e.nom_complet COLLATE NOCASE ASC
        LIMIT ?
        """,
        params,
    ).fetchall()

    return [
        {
            "id": int(row["id"]),
            "nom": row["nom_complet"],
            "niveau": row["niveau"],
            "previous_average": float(row["previous_average"] or 0),
            "current_average": float(row["current_average"] or 0),
            "delta": float(row["delta"] or 0),
        }
        for row in rows
    ]

def get_class_evolution(user_id, subject_id, school_year):
    """
    Récupère l'évolution de la moyenne de classe par trimestre.
    Retourne: { 'classes': ['6A', '5B'], 't1': [12.5, 11.0], 't2': [...], 't3': [...] }
    """
    db = get_db()
    
    # Formules pour chaque trimestre
    m1 = note_expr("1", "n1")[4]
    m2 = note_expr("2", "n2")[4]
    m3 = note_expr("3", "n3")[4]

    rows = db.execute(
        f"""
        SELECT 
          e.niveau,
          AVG(CASE WHEN {m1} IS NOT NULL THEN {m1} END) as avg_t1,
          AVG(CASE WHEN {m2} IS NOT NULL THEN {m2} END) as avg_t2,
          AVG(CASE WHEN {m3} IS NOT NULL THEN {m3} END) as avg_t3,
          COUNT(*) as count
        FROM eleves e
        LEFT JOIN notes n1 ON n1.user_id = e.user_id AND n1.eleve_id = e.id AND n1.subject_id = ? AND n1.trimestre = 1
        LEFT JOIN notes n2 ON n2.user_id = e.user_id AND n2.eleve_id = e.id AND n2.subject_id = ? AND n2.trimestre = 2
        LEFT JOIN notes n3 ON n3.user_id = e.user_id AND n3.eleve_id = e.id AND n3.subject_id = ? AND n3.trimestre = 3
        WHERE e.user_id = ? AND e.school_year = ?
        GROUP BY e.niveau
        ORDER BY e.niveau COLLATE NOCASE ASC
        """,
        (subject_id, subject_id, subject_id, user_id, school_year)
    ).fetchall()

    return {
        'labels': [r['niveau'] for r in rows],
        't1': [round(r['avg_t1'], 2) if r['avg_t1'] is not None else None for r in rows],
        't2': [round(r['avg_t2'], 2) if r['avg_t2'] is not None else None for r in rows],
        't3': [round(r['avg_t3'], 2) if r['avg_t3'] is not None else None for r in rows],
        'counts': [r['count'] for r in rows]
    }

def get_best_students_evolution(user_id, subject_id, school_year, limit=5):
    """
    Récupère les meilleurs élèves (moyenne annuelle) et leur évolution.
    """
    db = get_db()
    
    m1 = note_expr("1", "n1")[4]
    m2 = note_expr("2", "n2")[4]
    m3 = note_expr("3", "n3")[4]
    
    # Moyenne annuelle (approximative si notes manquantes)
    m_annual = f"(COALESCE({m1},0) + COALESCE({m2},0) + COALESCE({m3},0)) / (CASE WHEN {m1} IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN {m2} IS NOT NULL THEN 1 ELSE 0 END + CASE WHEN {m3} IS NOT NULL THEN 1 ELSE 0 END)"

    rows = db.execute(
        f"""
        SELECT 
          e.nom_complet,
          e.niveau,
          {m1} as moy1,
          {m2} as moy2,
          {m3} as moy3,
          {m_annual} as annual
        FROM eleves e
        LEFT JOIN notes n1 ON n1.user_id = e.user_id AND n1.eleve_id = e.id AND n1.subject_id = ? AND n1.trimestre = 1
        LEFT JOIN notes n2 ON n2.user_id = e.user_id AND n2.eleve_id = e.id AND n2.subject_id = ? AND n2.trimestre = 2
        LEFT JOIN notes n3 ON n3.user_id = e.user_id AND n3.eleve_id = e.id AND n3.subject_id = ? AND n3.trimestre = 3
        WHERE e.user_id = ? AND e.school_year = ? AND ({m1} IS NOT NULL OR {m2} IS NOT NULL OR {m3} IS NOT NULL)
        ORDER BY annual DESC
        LIMIT ?
        """,
        (subject_id, subject_id, subject_id, user_id, school_year, limit)
    ).fetchall()

    return [
        {
            'nom': r['nom_complet'],
            'niveau': r['niveau'],
            't1': round(r['moy1'], 2) if r['moy1'] is not None else None,
            't2': round(r['moy2'], 2) if r['moy2'] is not None else None,
            't3': round(r['moy3'], 2) if r['moy3'] is not None else None,
            'annual': round(r['annual'] or 0, 2)
        }
        for r in rows
    ]
