from flask import Blueprint, request, session, redirect, url_for, flash
from core.audit import log_change
from core.db import get_db
from core.security import login_required, write_required
from core.utils import clean_note, get_appreciation_dynamique
from edumaster.services.common import get_subjects, select_subject_id, parse_trim
from edumaster.services.grading import clean_component, split_activite_components, sum_activite_components

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

    db = get_db()
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.form.get("subject"))

    cur = db.execute(
        f"INSERT INTO eleves (user_id, nom_complet, niveau, remarques_t{trim}, devoir_t{trim}, activite_t{trim}, compo_t{trim}, parent_phone, parent_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            request.form["nom_complet"],
            request.form["niveau"],
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
    return redirect(request.referrer or url_for("dashboard.index", trimestre=trim))


@bp.route("/supprimer_multi", methods=["POST"])
@login_required
@write_required
def supprimer_multi():
    ids = request.form.getlist("ids")
    if ids:
        db = get_db()
        db.execute(
            f"DELETE FROM notes WHERE eleve_id IN ({','.join('?'*len(ids))}) AND user_id = ?",
            ids + [session["user_id"]],
        )
        db.execute(
            f"DELETE FROM eleves WHERE id IN ({','.join('?'*len(ids))}) AND user_id = ?",
            ids + [session["user_id"]],
        )
        db.commit()
        log_change("delete_students", session["user_id"], details=f"{len(ids)} eleves")
        flash(f"Supprimes ({len(ids)})", "success")
    return redirect(request.referrer or url_for("dashboard.index"))
