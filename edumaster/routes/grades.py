import json
from datetime import datetime
from flask import Blueprint, request, session, redirect, url_for, flash, jsonify, render_template, current_app
from core.db import get_db
from core.i18n import t
from core.security import login_required, write_required
from edumaster.services.common import get_subjects, get_user_assignment_scope, parse_trim, resolve_school_year, select_subject_id
from edumaster.services.grade_editor import GradeError, save_grades, undo_revision

bp = Blueprint('grades', __name__)


def error_message(code):
    messages = {
        'invalid_note': ('Chaque note doit être un nombre entre 0 et 20, ou une case vide.', 'يجب أن تكون كل علامة عدداً بين 0 و20 أو خانة فارغة.'),
        'conflict': ('Ces notes ont changé dans un autre onglet ou après un import. Vos saisies sont conservées ici : comparez-les avec la version actuelle avant de réessayer.', 'تغيّرت هذه العلامات في نافذة أخرى أو بعد استيراد. إدخالاتك محفوظة هنا: قارنها بالنسخة الحالية قبل المحاولة مجدداً.'),
        'forbidden': ('Cet élève ou cette matière ne fait pas partie de vos affectations.', 'هذا التلميذ أو هذه المادة خارج إسناداتك.'),
        'invalid_request': ('La demande est incomplète. Aucune note n’a été modifiée.', 'الطلب غير مكتمل. لم يتم تعديل أي علامة.'),
        'save_failed': ('Échec de l’enregistrement. Aucune note de cet envoi n’a été modifiée. Réessayez.', 'فشل الحفظ. لم يتم تعديل أي علامة من هذا الإرسال. أعد المحاولة.'),
    }
    return t(*messages.get(code, messages['save_failed']))


def scope_for(db, year):
    return ({'restricted': False, 'subject_ids': set(), 'classes': set()} if session.get('is_admin')
            else get_user_assignment_scope(db, session['user_id'], year))


@bp.post('/sauvegarder_tout')
@login_required
@write_required
def sauvegarder_tout():
    db = get_db()
    payload = request.get_json(silent=True) if request.is_json else request.form
    if not isinstance(payload, dict) and request.is_json:
        return jsonify(error='invalid_request', message=error_message('invalid_request')), 400
    payload = payload or {}
    year = resolve_school_year(db, payload.get('school_year'), is_admin=bool(session.get('is_admin')))
    trim = parse_trim(payload.get('trimestre_save'))
    subjects = get_subjects(db, session['user_id'])
    subject_id = select_subject_id(subjects, payload.get('subject'))
    rows = payload.get('rows') if request.is_json else []
    try:
        if str(payload.get('subject')) != str(subject_id):
            raise GradeError('forbidden')
        if not request.is_json:
            fields = ('activite', 'devoir', 'compo', 'status', 'version')
            lists = {key: request.form.getlist(key) for key in fields}
            for i, student_id in enumerate(request.form.getlist('id_eleve')):
                item = {'id': student_id}
                for key, values in lists.items():
                    if i < len(values):
                        item[key] = int(values[i]) if key == 'version' else values[i]
                rows.append(item)
        saved = save_grades(db, session['user_id'], year, subject_id, trim, scope_for(db, year), rows,
                            require_version=request.is_json)
    except (GradeError, ValueError) as error:
        code = error.code if isinstance(error, GradeError) else 'invalid_request'
        status = 409 if code == 'conflict' else 403 if code == 'forbidden' else 400
        message = error_message(code)
        if request.is_json:
            return jsonify(error=code, message=message, student_id=getattr(error, 'student_id', None)), status
        return render_template('save_error.html', message=message, rows=rows, year=year, trim=trim, subject_id=subject_id), status
    except Exception:
        current_app.logger.exception('Grade transaction failed')
        if request.is_json:
            return jsonify(error='save_failed', message=error_message('save_failed')), 500
        return render_template('save_error.html', message=error_message('save_failed'), rows=rows,
                               year=year, trim=trim, subject_id=subject_id), 500
    if request.is_json:
        return jsonify(saved=saved)
    flash(t('Notes enregistrées.', 'تم حفظ العلامات.'), 'success')
    return redirect(url_for('dashboard.index', trimestre=trim, subject=subject_id, school_year=year))


@bp.get('/history/grades')
@login_required
def revisions():
    db = get_db()
    rows = db.execute('''SELECT r.*, n.version AS current_version FROM grade_revisions r
        LEFT JOIN notes n ON n.eleve_id=r.eleve_id AND n.user_id=r.user_id
            AND n.subject_id=r.subject_id AND n.trimestre=r.trimestre
        WHERE r.user_id=? ORDER BY r.id DESC LIMIT 200''', (session['user_id'],)).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        item['time'] = datetime.fromtimestamp(item['created_at']).strftime('%Y-%m-%d %H:%M')
        item['before'] = json.loads(item['before_json']) or {}
        item['after'] = json.loads(item['after_json'])
        entries.append(item)
    return render_template('grade_history.html', revisions=entries, can_edit=session.get('role') != 'read_only')


@bp.post('/history/grades/<int:revision_id>/undo')
@login_required
@write_required
def undo(revision_id):
    db = get_db()
    revision = db.execute('SELECT school_year FROM grade_revisions WHERE id=? AND user_id=?',
                          (revision_id, session['user_id'])).fetchone()
    try:
        if not revision:
            raise GradeError('forbidden')
        undo_revision(db, session['user_id'], revision_id, scope_for(db, revision['school_year']))
        flash(t('Modification annulée. Les anciennes notes sont rétablies.', 'تم التراجع عن التعديل واستعادة العلامات السابقة.'), 'success')
    except GradeError as error:
        flash(error_message(error.code), 'warning')
    return redirect(url_for('grades.revisions'))
