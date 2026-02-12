from datetime import datetime
import csv
from io import BytesIO, StringIO
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, send_file

from core.audit import log_change
from core.db import get_db
from core.security import login_required, write_required
from core.utils import get_appreciation_dynamique

from edumaster.services.common import school_year, get_subjects, select_subject_id
from edumaster.services.filters import build_filters, build_history_filters
from edumaster.services.grading import note_expr, split_activite_components
from edumaster.services.stats_service import get_class_evolution, get_best_students_evolution

bp = Blueprint("dashboard", __name__)

@bp.route("/lang/<lang>")
def set_lang(lang: str):
    selected = (lang or "").strip().lower()
    if selected not in ("fr", "ar"):
        selected = "fr"
    session["lang"] = selected
    if session.get("user_id"):
        return redirect(request.referrer or url_for("dashboard.index"))
    return redirect(request.referrer or url_for("auth.login"))

@bp.route("/")
@login_required
def index():
    user_id = session["user_id"]
    trim = request.args.get("trimestre", "1")
    if trim not in ("1", "2", "3"):
        trim = "1"

    db = get_db()
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    subject_name = next(s["name"] for s in subjects if int(s["id"]) == subject_id)
    role = session.get("role") or ("admin" if session.get("is_admin") else "prof")
    can_edit = role != "read_only"

    devoir_expr, activite_expr, compo_expr, remarques_expr, moy_expr = note_expr(trim)
    filters = build_filters(user_id, trim, request.args, moy_expr)
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

    eleves_list = []
    for r in rows:
        p = float(r["participation"] or 0)
        b = float(r["comportement"] or 0)
        k = float(r["cahier"] or 0)
        pr = float(r["projet"] or 0)
        ao = float(r["assiduite_outils"] or 0)
        activite_value = float(r["activite"] or 0)
        if activite_value > 0 and p == 0 and b == 0 and k == 0 and pr == 0 and ao == 0:
            p, b, k, pr, ao = split_activite_components(activite_value)

        eleves_list.append(
            {
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
            }
        )

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

    risk_where = "e.user_id = ?"
    risk_params = [user_id]
    if niveau and niveau != "all":
        risk_where += " AND e.niveau = ?"
        risk_params.append(niveau)
    if search:
        risk_where += " AND e.nom_complet LIKE ?"
        risk_params.append(f"%{search}%")

    risk_count_row = db.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {risk_where} AND {moy_expr} > 0 AND {moy_expr} < 10
        """,
        join_params + risk_params,
    ).fetchone()
    risk_count = int(risk_count_row["c"] or 0)

    risk_rows = db.execute(
        f"""
        SELECT
          e.id,
          e.nom_complet,
          e.niveau,
          ROUND({moy_expr}, 2) AS moyenne
        FROM eleves e
        LEFT JOIN notes n ON n.user_id = e.user_id AND n.eleve_id = e.id AND n.subject_id = ? AND n.trimestre = ?
        WHERE {risk_where} AND {moy_expr} > 0 AND {moy_expr} < 10
        ORDER BY moyenne ASC, e.nom_complet ASC
        LIMIT 8
        """,
        join_params + risk_params,
    ).fetchall()
    risk_students = [
        {
            "id": int(r["id"]),
            "nom": r["nom_complet"],
            "niveau": r["niveau"],
            "moyenne": float(r["moyenne"] or 0),
        }
        for r in risk_rows
    ]

    progress_where = "e.user_id = ?"
    progress_params = [user_id]
    if niveau and niveau != "all":
        progress_where += " AND e.niveau = ?"
        progress_params.append(niveau)
    if search:
        progress_where += " AND e.nom_complet LIKE ?"
        progress_params.append(f"%{search}%")

    m1 = "((COALESCE(n1.devoir, e.devoir_t1) + COALESCE(n1.activite, e.activite_t1))/2.0 + (COALESCE(n1.compo, e.compo_t1) * 2.0))/3.0"
    m2 = "((COALESCE(n2.devoir, e.devoir_t2) + COALESCE(n2.activite, e.activite_t2))/2.0 + (COALESCE(n2.compo, e.compo_t2) * 2.0))/3.0"
    m3 = "((COALESCE(n3.devoir, e.devoir_t3) + COALESCE(n3.activite, e.activite_t3))/2.0 + (COALESCE(n3.compo, e.compo_t3) * 2.0))/3.0"

    progress_rows = db.execute(
        f"""
        SELECT
          e.niveau,
          AVG(CASE WHEN {m1} > 0 THEN {m1} END) AS t1,
          AVG(CASE WHEN {m2} > 0 THEN {m2} END) AS t2,
          AVG(CASE WHEN {m3} > 0 THEN {m3} END) AS t3
        FROM eleves e
        LEFT JOIN notes n1 ON n1.user_id = e.user_id AND n1.eleve_id = e.id AND n1.subject_id = ? AND n1.trimestre = 1
        LEFT JOIN notes n2 ON n2.user_id = e.user_id AND n2.eleve_id = e.id AND n2.subject_id = ? AND n2.trimestre = 2
        LEFT JOIN notes n3 ON n3.user_id = e.user_id AND n3.eleve_id = e.id AND n3.subject_id = ? AND n3.trimestre = 3
        WHERE {progress_where}
        GROUP BY e.niveau
        ORDER BY e.niveau COLLATE NOCASE ASC
        """,
        [subject_id, subject_id, subject_id] + progress_params,
    ).fetchall()

    progress_labels = [str(r["niveau"]) for r in progress_rows]
    progress_t1 = [round(float(r["t1"] or 0), 2) for r in progress_rows]
    progress_t2 = [round(float(r["t2"] or 0), 2) for r in progress_rows]
    progress_t3 = [round(float(r["t3"] or 0), 2) for r in progress_rows]

    chart_data = {
        "classes": {"labels": class_labels, "values": class_avgs},
        "distribution": {"labels": ["Admis", "Echec", "Non saisi"], "values": dist_values},
        "progression": {
            "labels": progress_labels,
            "t1": progress_t1,
            "t2": progress_t2,
            "t3": progress_t3,
        },
    }

    base_args = dict(request.args)
    base_args.pop("page", None)
    risk_args = dict(request.args)
    risk_args["etat"] = "echec"
    risk_args.pop("page", None)
    risk_url = url_for("dashboard.index", **risk_args)

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
        risk_students=risk_students,
        risk_count=risk_count,
        risk_url=risk_url,
        subjects=subjects,
        subject_id=subject_id,
        subject_name=subject_name,
        can_edit=can_edit,
        school_year=school_year(datetime.now()),
        school_name=session.get("school_name"),
    )

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
    subjects = get_subjects(db, user_id)

    filters = build_history_filters(user_id, request.args)
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

    export_url = url_for("dashboard.history_export", **dict(request.args))
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

    filters = build_history_filters(user_id, request.args)
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

    text_out = StringIO(newline="")
    writer = csv.writer(text_out)
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
    payload = text_out.getvalue().encode("utf-8-sig")
    output = BytesIO(payload)
    output.seek(0)

    filename = f"historique_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return send_file(output, as_attachment=True, download_name=filename, mimetype="text/csv")

@bp.route("/settings", methods=["GET", "POST"])
@login_required
@write_required
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
@write_required
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
        {"key": "sun", "label": "Dimanche"},
        {"key": "mon", "label": "Lundi"},
        {"key": "tue", "label": "Mardi"},
        {"key": "wed", "label": "Mercredi"},
        {"key": "thu", "label": "Jeudi"},
    ]
    slots = [
        {"key": "s1", "label": "08:00-09:00"},
        {"key": "s2", "label": "09:00-10:00"},
        {"key": "s3", "label": "10:00-11:00"},
        {"key": "s4", "label": "11:00-12:00"},
        {"key": "s5", "label": "12:00-13:00"},
        {"key": "s6", "label": "13:00-14:00"},
        {"key": "s7", "label": "14:00-15:00"},
        {"key": "s8", "label": "15:00-16:00"},
        {"key": "s9", "label": "16:00-17:00"},
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
        return redirect(url_for("dashboard.timetable", niveau=niveau))

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


@bp.route("/stats")
@login_required
def stats():
    user_id = session["user_id"]
    db = get_db()
    
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    
    # Handle case where no subjects exist
    if not subjects:
        flash("Ajoutez d'abord une matiere.", "warning")
        return redirect(url_for("dashboard.subjects"))
        
    subject_name = next((s["name"] for s in subjects if int(s["id"]) == subject_id), "Matière inconnue")
    
    evolution = get_class_evolution(user_id, subject_id)
    # Convert set to list for template if necessary, but it's a list already
    
    # Get top students
    top_students = get_best_students_evolution(user_id, subject_id, limit=5)

    return render_template(
        "stats.html",
        subjects=subjects,
        subject_id=subject_id,
        subject_name=subject_name,
        evolution=evolution,
        top_students=top_students
    )


@bp.route("/subjects", methods=["GET", "POST"])
@login_required
@write_required
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
                return redirect(url_for("dashboard.index"))
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
@write_required
def delete_subject(subject_id: int):
    user_id = session["user_id"]
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) as c FROM subjects WHERE user_id = ?",
        (user_id,),
    ).fetchone()["c"]
    if count <= 1:
        flash("Impossible de supprimer la derniere matiere", "warning")
        return redirect(url_for("dashboard.subjects"))

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
    return redirect(url_for("dashboard.subjects"))
