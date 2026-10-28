from datetime import datetime
import csv
from io import BytesIO, StringIO
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, send_file

from core.audit import log_change
from core.db import get_db
from core.security import login_required, write_required
from core.utils import get_appreciation_dynamique

from edumaster.services.common import (
    get_active_school_year,
    get_subjects,
    get_user_assignment_scope,
    list_school_years,
    resolve_school_year,
    select_subject_id,
)
from edumaster.services.dashboard_service import compute_stats_summary, fetch_students_page, compute_chart_data
from edumaster.services.filters import build_filters, build_history_filters
from edumaster.services.grading import note_expr, split_activite_components
from edumaster.services.stats_service import (
    get_best_students_evolution,
    get_class_evolution,
    get_declining_students,
)

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
    role = session.get("role") or ("admin" if session.get("is_admin") else "prof")
    can_edit = role != "read_only"
    is_admin = bool(session.get("is_admin"))

    selected_school_year = resolve_school_year(
        db,
        request.args.get("school_year"),
        is_admin=is_admin,
    )
    assignment_scope = (
        {"restricted": False, "subject_ids": set(), "classes": set()}
        if is_admin
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )

    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.args.get("subject"))
    if assignment_scope["restricted"] and subject_id not in assignment_scope["subject_ids"]:
        allowed_subjects = [s for s in subjects if int(s["id"]) in assignment_scope["subject_ids"]]
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
        allowed_classes=(assignment_scope["classes"] if assignment_scope["restricted"] else None),
    )
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
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? AND school_year = ? ORDER BY niveau",
            (user_id, selected_school_year),
        ).fetchall()
    ]
    if assignment_scope["restricted"]:
        classes = [c for c in classes if c in assignment_scope["classes"]]

    where = filters["where"]
    params = filters["params"]

    stats = compute_stats_summary(db, user_id, trim, subject_id, where, params)
    total = stats['nb_total']
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    eleves_list = fetch_students_page(db, user_id, trim, subject_id, where, params, sort, order, page, per_page)
    base_args = dict(request.args)
    base_args.pop('page', None)

    return render_template(
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
        stats=stats,
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
    selected_school_year = resolve_school_year(
        db,
        request.values.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    scope = (
        {"restricted": False, "classes": set()}
        if session.get("is_admin")
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )

    classes = [
        r["niveau"]
        for r in db.execute(
            "SELECT DISTINCT niveau FROM eleves WHERE user_id = ? AND school_year = ? ORDER BY niveau",
            (user_id, selected_school_year),
        ).fetchall()
    ]
    if scope["restricted"]:
        classes = [c for c in classes if c in scope["classes"]]

    niveau = request.values.get("niveau", "")
    if scope["restricted"] and niveau and niveau not in scope["classes"]:
        flash("Classe non autorisee pour ce compte.", "warning")
        return redirect(url_for("dashboard.timetable", school_year=selected_school_year))
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
        return redirect(url_for("dashboard.timetable", niveau=niveau, school_year=selected_school_year))

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
        school_year=selected_school_year,
        school_years=list_school_years(db),
        active_school_year=get_active_school_year(db),
    )


@bp.route("/stats")
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
    stats = compute_stats_summary(db, user_id, trim, subject_id, where, params)
    chart_data = compute_chart_data(db, user_id, trim, subject_id, where, params, niveau, search, assignment_scope, selected_school_year)
    top_eleves = chart_data['top_eleves']
    risk_students = chart_data['risk_students']
    risk_count = chart_data['risk_count']
    risk_args = dict(request.args)
    risk_args.update(etat='echec', school_year=selected_school_year)
    risk_args.pop('page', None)
    risk_url = url_for('dashboard.index', **risk_args)

    evolution = get_class_evolution(user_id, subject_id, selected_school_year)
    top_students_annual = get_best_students_evolution(user_id, subject_id, selected_school_year, limit=5)
    declining_students = get_declining_students(
        user_id,
        subject_id,
        selected_school_year,
        trim,
        niveau=niveau,
        allowed_classes=(assignment_scope["classes"] if assignment_scope["restricted"] else None),
        search=search,
    )

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
        declining_students=declining_students,
        trimestre=trim,
        niveau_actuel=niveau,
        liste_classes=all_classes,
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
