import json
import time
from flask import render_template
from core.i18n import t
from edumaster.services.grading import optional_note, assessment_state
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
    d = optional_note(request.form.get("devoir"))
    c = optional_note(request.form.get("compo"))
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
    if not any([p_raw, b_raw, k_raw, pr_raw, ao_raw]) and not request.form.get('activite'):
        a = None
    assessment_status = assessment_state(a, d, c)
    moy = ((d + a) / 2 + (c * 2)) / 3 if assessment_status == 'graded' else None

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
                (get_appreciation_dynamique(moy, user_id) if moy is not None else ""),
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
            (user_id, eleve_id, subject_id, int(trim), p, b, k, pr, ao, a, d, c, (get_appreciation_dynamique(moy, user_id) if moy is not None else "")),
        )

        db.execute('UPDATE notes SET assessment_status=? WHERE eleve_id=? AND user_id=? AND subject_id=? AND trimestre=?',
                   (assessment_status, eleve_id, user_id, subject_id, int(trim)))
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
            for archived_id in allowed_ids:
                student = dict(db.execute('SELECT * FROM eleves WHERE id=? AND user_id=?', (archived_id, user_id)).fetchone())
                marks = [dict(r) for r in db.execute('SELECT * FROM notes WHERE eleve_id=? AND user_id=?', (archived_id, user_id))]
                db.execute('''INSERT INTO student_trash(user_id,student_id,student_name,school_year,niveau,payload,created_at)
                    VALUES (?,?,?,?,?,?,?)''', (user_id, student['id'], student['nom_complet'], selected_school_year,
                    student['niveau'], json.dumps(dict(student=student, notes=marks), ensure_ascii=False), int(time.time())))
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
            flash(t('Élèves déplacés dans la corbeille : ', 'تم نقل التلاميذ إلى السلة: ') + str(len(allowed_ids)), 'success')
        except Exception:
            db.rollback()
            flash("Erreur lors de la suppression.", "danger")
    return redirect(request.referrer or url_for("dashboard.index", school_year=selected_school_year))


@bp.route("/modifier_eleve_nom", methods=["POST"])
@login_required
@write_required
def modifier_eleve_nom():
    user_id = session["user_id"]
    db = get_db()
    
    eleve_id = request.form.get("eleve_id")
    nouveau_nom = (request.form.get("nouveau_nom") or "").strip()
    
    if not eleve_id or not nouveau_nom:
        flash("Informations manquantes pour la modification du nom.", "warning")
        return redirect(request.referrer or url_for("dashboard.index"))
        
    try:
        # Verify the student belongs to the user
        eleve = db.execute(
            "SELECT id FROM eleves WHERE id = ? AND user_id = ?",
            (eleve_id, user_id)
        ).fetchone()
        
        if not eleve:
            flash("Élève introuvable ou vous n'avez pas la permission de le modifier.", "danger")
            return redirect(request.referrer or url_for("dashboard.index"))
            
        db.execute(
            "UPDATE eleves SET nom_complet = ? WHERE id = ? AND user_id = ?",
            (nouveau_nom, eleve_id, user_id)
        )
        db.commit()
        flash("Nom de l'élève mis à jour avec succès.", "success")
        log_change("edit_student_name", user_id, details=nouveau_nom, eleve_id=eleve_id)
    except Exception as e:
        db.rollback()
        flash("Erreur lors de la mise à jour du nom.", "danger")
        
    return redirect(request.referrer or url_for("dashboard.index"))


@bp.get('/trash')
@login_required
def trash():
    db = get_db()
    rows = db.execute('SELECT id,student_name,school_year,niveau,created_at FROM student_trash WHERE user_id=? ORDER BY id DESC',
                      (session['user_id'],)).fetchall()
    return render_template('trash.html', entries=rows, can_edit=session.get('role') != 'read_only')


@bp.post('/trash/<int:trash_id>/restore')
@login_required
@write_required
def restore_student(trash_id):
    user_id = session['user_id']
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        entry = db.execute('SELECT * FROM student_trash WHERE id=? AND user_id=?', (trash_id, user_id)).fetchone()
        if not entry:
            db.rollback()
            flash(t('Élève introuvable.', 'التلميذ غير موجود.'), 'warning')
            return redirect(url_for('students.trash'))
        scope = ({'restricted': False, 'classes': set()} if session.get('is_admin')
                 else get_user_assignment_scope(db, user_id, entry['school_year']))
        if scope['restricted'] and entry['niveau'] not in scope['classes']:
            db.rollback()
            flash(t('Classe non autorisée.', 'القسم غير مسموح.'), 'warning')
            return redirect(url_for('students.trash'))
        data = json.loads(entry['payload'])
        student = data['student']
        if db.execute('SELECT 1 FROM eleves WHERE id=? OR (user_id=? AND school_year=? AND niveau=? AND nom_complet=?)',
                      (student['id'], user_id, student['school_year'], student['niveau'], student['nom_complet'])).fetchone():
            db.rollback()
            flash(t('Un élève correspondant existe déjà. Aucun dossier n’a été écrasé.', 'يوجد تلميذ مطابق بالفعل. لم يتم استبدال أي ملف.'), 'warning')
            return redirect(url_for('students.trash'))
        columns = {r['name'] for r in db.execute('PRAGMA table_info(eleves)')}
        keys = [key for key in student if key in columns]
        db.execute('INSERT INTO eleves ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')', tuple(student[k] for k in keys))
        columns = {r['name'] for r in db.execute('PRAGMA table_info(notes)')}
        for note in data['notes']:
            # Keep student identities and advance versions beyond any editor opened before deletion.
            keys = [key for key in note if key in columns and key != 'id']
            if 'version' in note:
                note['version'] += 1
            db.execute('INSERT INTO notes ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')', tuple(note[k] for k in keys))
        db.execute('DELETE FROM student_trash WHERE id=? AND user_id=?', (trash_id, user_id))
        db.commit()
        log_change('restore_student', user_id, details=student['nom_complet'], eleve_id=student['id'])
        flash(t('Élève et notes restaurés.', 'تم استرجاع التلميذ وعلاماته.'), 'success')
    except Exception:
        db.rollback()
        flash(t('Restauration impossible. Le dossier reste dans la corbeille.', 'تعذّر الاسترجاع. يبقى الملف في السلة.'), 'danger')
    return redirect(url_for('students.trash'))
