from core.db import get_db
from edumaster.services.grading import note_expr

def get_class_evolution(user_id, subject_id):
    """
    Récupère l'évolution de la moyenne de classe par trimestre.
    Retourne: { 'classes': ['6A', '5B'], 't1': [12.5, 11.0], 't2': [...], 't3': [...] }
    """
    db = get_db()
    
    # Formules pour chaque trimestre
    m1 = "((COALESCE(n1.devoir, e.devoir_t1) + COALESCE(n1.activite, e.activite_t1))/2.0 + (COALESCE(n1.compo, e.compo_t1) * 2.0))/3.0"
    m2 = "((COALESCE(n2.devoir, e.devoir_t2) + COALESCE(n2.activite, e.activite_t2))/2.0 + (COALESCE(n2.compo, e.compo_t2) * 2.0))/3.0"
    m3 = "((COALESCE(n3.devoir, e.devoir_t3) + COALESCE(n3.activite, e.activite_t3))/2.0 + (COALESCE(n3.compo, e.compo_t3) * 2.0))/3.0"

    rows = db.execute(
        f"""
        SELECT 
          e.niveau,
          AVG(CASE WHEN {m1} > 0 THEN {m1} END) as avg_t1,
          AVG(CASE WHEN {m2} > 0 THEN {m2} END) as avg_t2,
          AVG(CASE WHEN {m3} > 0 THEN {m3} END) as avg_t3,
          COUNT(*) as count
        FROM eleves e
        LEFT JOIN notes n1 ON n1.user_id = e.user_id AND n1.eleve_id = e.id AND n1.subject_id = ? AND n1.trimestre = 1
        LEFT JOIN notes n2 ON n2.user_id = e.user_id AND n2.eleve_id = e.id AND n2.subject_id = ? AND n2.trimestre = 2
        LEFT JOIN notes n3 ON n3.user_id = e.user_id AND n3.eleve_id = e.id AND n3.subject_id = ? AND n3.trimestre = 3
        WHERE e.user_id = ?
        GROUP BY e.niveau
        ORDER BY e.niveau COLLATE NOCASE ASC
        """,
        (subject_id, subject_id, subject_id, user_id)
    ).fetchall()

    return {
        'labels': [r['niveau'] for r in rows],
        't1': [round(r['avg_t1'] or 0, 2) for r in rows],
        't2': [round(r['avg_t2'] or 0, 2) for r in rows],
        't3': [round(r['avg_t3'] or 0, 2) for r in rows],
        'counts': [r['count'] for r in rows]
    }

def get_best_students_evolution(user_id, subject_id, limit=5):
    """
    Récupère les meilleurs élèves (moyenne annuelle) et leur évolution.
    """
    db = get_db()
    
    m1 = "((COALESCE(n1.devoir, e.devoir_t1) + COALESCE(n1.activite, e.activite_t1))/2.0 + (COALESCE(n1.compo, e.compo_t1) * 2.0))/3.0"
    m2 = "((COALESCE(n2.devoir, e.devoir_t2) + COALESCE(n2.activite, e.activite_t2))/2.0 + (COALESCE(n2.compo, e.compo_t2) * 2.0))/3.0"
    m3 = "((COALESCE(n3.devoir, e.devoir_t3) + COALESCE(n3.activite, e.activite_t3))/2.0 + (COALESCE(n3.compo, e.compo_t3) * 2.0))/3.0"
    
    # Moyenne annuelle (approximative si notes manquantes)
    m_annual = f"(COALESCE({m1},0) + COALESCE({m2},0) + COALESCE({m3},0)) / (CASE WHEN {m1}>0 THEN 1 ELSE 0 END + CASE WHEN {m2}>0 THEN 1 ELSE 0 END + CASE WHEN {m3}>0 THEN 1 ELSE 0 END)"

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
        WHERE e.user_id = ?
        ORDER BY annual DESC
        LIMIT ?
        """,
        (subject_id, subject_id, subject_id, user_id, limit)
    ).fetchall()

    return [
        {
            'nom': r['nom_complet'],
            'niveau': r['niveau'],
            't1': round(r['moy1'] or 0, 2),
            't2': round(r['moy2'] or 0, 2),
            't3': round(r['moy3'] or 0, 2),
            'annual': round(r['annual'] or 0, 2)
        }
        for r in rows
    ]
