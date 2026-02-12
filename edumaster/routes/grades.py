from flask import Blueprint, request, session, redirect, url_for, flash
from core.audit import log_change
from core.db import get_db
from core.security import login_required, write_required
from core.utils import clean_note, get_appreciation_dynamique
from edumaster.services.common import get_subjects, select_subject_id, parse_trim
from edumaster.services.grading import clean_component, split_activite_components, sum_activite_components, safe_list_get

bp = Blueprint("grades", __name__)

@bp.route("/sauvegarder_tout", methods=["POST"])
@login_required
@write_required
def sauvegarder_tout():
    user_id = session["user_id"]
    trim = parse_trim(request.form.get("trimestre_save"))
    db = get_db()
    subjects = get_subjects(db, user_id)
    subject_id = select_subject_id(subjects, request.form.get("subject"))

    ids = request.form.getlist("id_eleve")
    devs = request.form.getlist("devoir")
    acts = request.form.getlist("activite")
    comps = request.form.getlist("compo")
    participations = request.form.getlist("participation")
    comportements = request.form.getlist("comportement")
    cahiers = request.form.getlist("cahier")
    projets = request.form.getlist("projet")
    assiduites = request.form.getlist("assiduite_outils")
    use_components = any([participations, comportements, cahiers, projets, assiduites])

    updated = 0
    for i in range(len(ids)):
        try:
            d = clean_note(safe_list_get(devs, i))
            c = clean_note(safe_list_get(comps, i))
            if use_components:
                p = clean_component(safe_list_get(participations, i), 3)
                b = clean_component(safe_list_get(comportements, i), 6)
                k = clean_component(safe_list_get(cahiers, i), 5)
                pr = clean_component(safe_list_get(projets, i), 4)
                ao = clean_component(safe_list_get(assiduites, i), 2)
            else:
                p, b, k, pr, ao = split_activite_components(safe_list_get(acts, i))
            a = sum_activite_components(p, b, k, pr, ao)
            moy = ((d + a) / 2 + (c * 2)) / 3
            rem = get_appreciation_dynamique(moy, user_id)
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
                (user_id, ids[i], subject_id, int(trim), p, b, k, pr, ao, a, d, c, rem),
            )
            updated += 1
        except Exception:
            continue
    db.commit()
    log_change("update_notes", user_id, details=f"{updated} lignes", subject_id=subject_id)
    flash("Notes enregistrees.", "success")
    return redirect(request.referrer or url_for("dashboard.index", trimestre=trim))
