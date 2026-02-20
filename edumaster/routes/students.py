from flask import Blueprint, request, session, redirect, url_for, flash
from core.audit import log_change
from core.db import get_db
from core.security import login_required, write_required
from core.utils import clean_note, get_appreciation_dynamique
from edumaster.services.common import (
    get_subjects,
    get_user_assignment_scope,
    parse_trim,
    resolve_school_year,
    select_subject_id,
)
from edumaster.services.grading import clean_component, split_activite_components, sum_activite_components, trim_columns

bp = Blueprint("students", __name__)

@bp.route("/ajouter_eleve", methods=["POST"])
@login_required
@write_required
def ajouter_eleve():
    user_id = session["user_id"]
    trim = parse_trim(request.form.get("trimestre_ajout", "1"))
    d = clean_note(request.form.get("devoir"))
    c = clean_note(request.form.get("compo"))
    p_raw = (request.form.get("participation") or "").strip()
    b_raw = (request.form.get("comportement") or "").strip()
    k_raw = (request.form.get("cahier") or "").strip()
    pr_raw = (request.form.get("projet") or "").strip()
    ao_raw = (request.form.get("assiduite_outils") or "").strip()
    if any([p_raw, b_raw, k_raw, pr_raw, ao_raw]):
        p = clean_component(p_raw, 3)
        b = clean_component(b_raw, 6)
        k = clean_component(k_raw, 5)
        pr = clean_component(pr_raw, 4)
        ao = clean_component(ao_raw, 2)
    else:
        p, b, k, pr, ao = split_activite_components(request.form.get("activite"))
    a = sum_activite_components(p, b, k, pr, ao)
    moy = ((d + a) / 2 + (c * 2)) / 3

    parent_phone = (request.form.get("parent_phone") or "").strip()
    parent_email = (request.form.get("parent_email") or "").strip()
    niveau = (request.form.get("niveau") or "").strip()

    db = get_db()
    selected_school_year = resolve_school_year(
        db,
        request.form.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    scope = (
        {"restricted": False, "subject_ids": set(), "classes": set()}
        if session.get("is_admin")
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.form.get("subject"))
    if scope["restricted"]:
        if subject_id not in scope["subject_ids"]:
            flash("Matiere non autorisee pour ce compte.", "warning")
            return redirect(request.referrer or url_for("dashboard.index", trimestre=trim, school_year=selected_school_year))
        if niveau not in scope["classes"]:
            flash("Classe non autorisee pour ce compte.", "warning")
            return redirect(request.referrer or url_for("dashboard.index", trimestre=trim, school_year=selected_school_year))

    # Use safe column mapping instead of f-string interpolation
    cols = trim_columns(trim)

    try:
        cur = db.execute(
            f"INSERT INTO eleves (user_id, school_year, nom_complet, niveau, "
            f"{cols['remarques']}, {cols['devoir']}, {cols['activite']}, {cols['compo']}, "
            f"parent_phone, parent_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                selected_school_year,
                request.form["nom_complet"],
                niveau,
                get_appreciation_dynamique(moy, user_id),
                d,
                a,
                c,
                parent_phone,
                parent_email,
            ),
        )
        eleve_id = cur.lastrowid

        db.execute(
            """
            INSERT INTO notes (
                user_id, eleve_id, subject_id, trimestre,
                participation, comportement, cahier, projet, assiduite_outils,
                activite, devoir, compo, remarques
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, eleve_id, subject_id, trimestre)
            DO UPDATE SET
                participation=excluded.participation,
                comportement=excluded.comportement,
                cahier=excluded.cahier,
                projet=excluded.projet,
                assiduite_outils=excluded.assiduite_outils,
                activite=excluded.activite,
                devoir=excluded.devoir,
                compo=excluded.compo,
                remarques=excluded.remarques
            """,
            (user_id, eleve_id, subject_id, int(trim), p, b, k, pr, ao, a, d, c, get_appreciation_dynamique(moy, user_id)),
        )

        db.commit()
        log_change("add_student", user_id, details=request.form.get("nom_complet", ""), eleve_id=eleve_id, subject_id=subject_id)
    except Exception:
        db.rollback()
        flash("Erreur lors de l'ajout de l'eleve.", "danger")

    return redirect(request.referrer or url_for("dashboard.index", trimestre=trim, school_year=selected_school_year))


@bp.route("/supprimer_multi", methods=["POST"])
@login_required
@write_required
def supprimer_multi():
    user_id = session["user_id"]
    db = get_db()
    selected_school_year = resolve_school_year(
        db,
        request.form.get("school_year"),
        is_admin=bool(session.get("is_admin")),
    )
    scope = (
        {"restricted": False, "classes": set()}
        if session.get("is_admin")
        else get_user_assignment_scope(db, user_id, selected_school_year)
    )
    ids = request.form.getlist("ids")
    if ids:
        placeholders = ",".join("?" * len(ids))
        params = ids + [user_id, selected_school_year]
        where_extra = ""
        if scope["restricted"] and scope["classes"]:
            class_placeholders = ",".join("?" * len(scope["classes"]))
            where_extra = f" AND niveau IN ({class_placeholders})"
            params += sorted(scope["classes"])
        allowed_rows = db.execute(
            f"SELECT id FROM eleves WHERE id IN ({placeholders}) AND user_id = ? AND school_year = ?{where_extra}",
            params,
        ).fetchall()
        allowed_ids = [str(r["id"]) for r in allowed_rows]
        if not allowed_ids:
            flash("Aucun eleve autorise pour suppression.", "warning")
            return redirect(request.referrer or url_for("dashboard.index", school_year=selected_school_year))
        del_placeholders = ",".join("?" * len(allowed_ids))
        try:
            db.execute(
                f"DELETE FROM notes WHERE eleve_id IN ({del_placeholders}) AND user_id = ?",
                allowed_ids + [user_id],
            )
            db.execute(
                f"DELETE FROM eleves WHERE id IN ({del_placeholders}) AND user_id = ? AND school_year = ?",
                allowed_ids + [user_id, selected_school_year],
            )
            db.commit()
            log_change("delete_students", user_id, details=f"{len(allowed_ids)} eleves")
            flash(f"Supprimes ({len(allowed_ids)})", "success")
        except Exception:
            db.rollback()
            flash("Erreur lors de la suppression.", "danger")
    return redirect(request.referrer or url_for("dashboard.index", school_year=selected_school_year))
