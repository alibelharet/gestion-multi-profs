from .grading import note_expr

def build_bulletin_multisubject(db, user_id: int, eleve_id: int, trim: str):
    eleve = db.execute(
        "SELECT * FROM eleves WHERE id = ? AND user_id = ?",
        (eleve_id, user_id),
    ).fetchone()
    if not eleve:
        return None

    subjects = db.execute(
        "SELECT id, name FROM subjects WHERE user_id = ? ORDER BY name COLLATE NOCASE",
        (user_id,),
    ).fetchall()
    if not subjects:
        db.execute(
            "INSERT INTO subjects (user_id, name) VALUES (?, ?)",
            (user_id, "Sciences"),
        )
        db.commit()

    devoir_expr, activite_expr, compo_expr, remarques_expr, _ = note_expr(trim)

    rows = db.execute(
        f"""
        SELECT
            s.id AS subject_id,
            s.name AS subject_name,
            {activite_expr} AS activite,
            {devoir_expr} AS devoir,
            {compo_expr} AS compo,
            {remarques_expr} AS remarques,
            ROUND((({devoir_expr} + {activite_expr})/2.0 + ({compo_expr} * 2.0))/3.0, 2) AS moyenne
        FROM subjects s
        LEFT JOIN eleves e
            ON e.id = ?
           AND e.user_id = s.user_id
        LEFT JOIN notes n
            ON n.user_id = s.user_id
           AND n.eleve_id = e.id
           AND n.subject_id = s.id
           AND n.trimestre = ?
        WHERE s.user_id = ?
        ORDER BY s.name COLLATE NOCASE
        """,
        (eleve_id, int(trim), user_id),
    ).fetchall()

    subject_lines = []
    for r in rows:
        subject_lines.append(
            {
                "subject_id": int(r["subject_id"]),
                "subject_name": r["subject_name"],
                "activite": float(r["activite"] or 0),
                "devoir": float(r["devoir"] or 0),
                "compo": float(r["compo"] or 0),
                "remarques": r["remarques"] or "",
                "moyenne": float(r["moyenne"] or 0),
            }
        )

    moyenne_generale = 0.0
    if subject_lines:
        moyenne_generale = round(
            sum(line["moyenne"] for line in subject_lines) / len(subject_lines),
            2,
        )

    class_rows = db.execute(
        f"""
        SELECT
            e.id,
            AVG(((COALESCE(n.devoir, e.devoir_t{trim}) + COALESCE(n.activite, e.activite_t{trim}))/2.0 + (COALESCE(n.compo, e.compo_t{trim}) * 2.0))/3.0) AS moyenne_generale
        FROM eleves e
        JOIN subjects s ON s.user_id = e.user_id
        LEFT JOIN notes n
            ON n.user_id = e.user_id
           AND n.eleve_id = e.id
           AND n.subject_id = s.id
           AND n.trimestre = ?
        WHERE e.user_id = ? AND e.niveau = ?
        GROUP BY e.id
        ORDER BY moyenne_generale DESC, e.nom_complet COLLATE NOCASE ASC
        """,
        (int(trim), user_id, eleve["niveau"]),
    ).fetchall()

    scores = [(int(r["id"]), float(r["moyenne_generale"] or 0)) for r in class_rows]
    rank = next((i + 1 for i, item in enumerate(scores) if item[0] == eleve_id), 1)
    moyenne_classe = round(
        sum(item[1] for item in scores) / len(scores), 2
    ) if scores else 0.0

    return {
        "eleve": eleve,
        "subject_lines": subject_lines,
        "moyenne_generale": moyenne_generale,
        "moyenne_classe": moyenne_classe,
        "rank": rank,
        "total_eleves": len(scores),
    }
