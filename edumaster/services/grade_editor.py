"""Atomic grade editing with optimistic concurrency and reversible revisions."""
import json
import time

from .grading import optional_note, assessment_state, split_activite_components, note_expr

SCORE_FIELDS = ('activite', 'devoir', 'compo')
COMPONENTS = ('participation', 'comportement', 'cahier', 'projet', 'assiduite_outils')
NOTE_FIELDS = (*COMPONENTS, *SCORE_FIELDS, 'remarques', 'assessment_status')


class GradeError(Exception):
    def __init__(self, code, student_id=None):
        self.code, self.student_id = code, student_id
        super().__init__(code)


def allowed_student(db, user_id, student_id, year, scope, subject_id):
    row = db.execute('SELECT * FROM eleves WHERE id=? AND user_id=? AND school_year=?',
                     (student_id, user_id, year)).fetchone()
    if not row or (scope['restricted'] and
                   (row['niveau'] not in scope['classes'] or subject_id not in scope['subject_ids'])):
        raise GradeError('forbidden', student_id)
    return row


def snapshot(row):
    return {key: row[key] for key in NOTE_FIELDS} if row else None


def write_note(db, user_id, student_id, subject_id, trim, data, version):
    fields = ','.join(NOTE_FIELDS)
    assignments = ','.join(f'{key}=excluded.{key}' for key in NOTE_FIELDS)
    placeholders = ','.join('?' for _ in range(len(NOTE_FIELDS) + 5))
    db.execute(f'''INSERT INTO notes(user_id,eleve_id,subject_id,trimestre,{fields},version)
        VALUES ({placeholders}) ON CONFLICT(user_id,eleve_id,subject_id,trimestre)
        DO UPDATE SET {assignments}, version=excluded.version''',
        (user_id, student_id, subject_id, int(trim), *(data[k] for k in NOTE_FIELDS), version))


def save_grades(db, user_id, year, subject_id, trim, scope, rows, require_version=True):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise GradeError('invalid_request')
    if not db.execute('SELECT 1 FROM subjects WHERE id=? AND user_id=?', (subject_id, user_id)).fetchone():
        raise GradeError('forbidden')
    results = []
    seen = set()
    db.commit()
    try:
        db.execute('BEGIN IMMEDIATE')
        rules = db.execute('SELECT * FROM appreciations WHERE user_id=? ORDER BY min_val', (user_id,)).fetchall()
        for item in rows:
            if not isinstance(item, dict) or any(key not in item for key in SCORE_FIELDS):
                raise GradeError('invalid_request')
            try:
                student_id = int(item['id'])
            except (TypeError, ValueError, KeyError):
                raise GradeError('invalid_request') from None
            if student_id in seen:
                raise GradeError('invalid_request', student_id)
            seen.add(student_id)
            student = allowed_student(db, user_id, student_id, year, scope, subject_id)
            current = db.execute('SELECT * FROM notes WHERE user_id=? AND eleve_id=? AND subject_id=? AND trimestre=?',
                                 (user_id, student_id, subject_id, int(trim))).fetchone()
            version = current['version'] if current else -1
            if require_version or 'version' in item:
                if item.get('version') != version:
                    raise GradeError('conflict', student_id)
            try:
                values = {key: optional_note(item.get(key)) for key in SCORE_FIELDS}
            except ValueError:
                raise GradeError('invalid_note', student_id) from None
            requested_status = item.get('status', 'auto')
            if requested_status not in ('auto', 'absent', 'graded', 'partial', 'not_entered'):
                raise GradeError('invalid_request', student_id)
            state = assessment_state(**values, absent=requested_status == 'absent')
            average = round(((values['activite'] + values['devoir']) / 2 + values['compo'] * 2) / 3, 2) if state == 'graded' else None
            remark = ''
            if average is not None:
                remark = next((r['message'] for r in rules if r['min_val'] <= average <= r['max_val']), '')
            components = split_activite_components(values['activite']) if values['activite'] is not None else (None,) * 5
            # Preserve real component assessments when the total did not change.
            if current and current['activite'] == values['activite']:
                components = tuple(current[k] for k in COMPONENTS)
            data = dict(zip(COMPONENTS, components), **values, remarques=remark, assessment_status=state)
            before = snapshot(current)
            revision_id = None
            if before != data:
                version = max(0, version) + 1
                write_note(db, user_id, student_id, subject_id, trim, data, version)
                cur = db.execute('''INSERT INTO grade_revisions(user_id,eleve_id,subject_id,trimestre,
                    school_year,student_name,before_json,after_json,after_version,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (user_id, student_id, subject_id, int(trim), year, student['nom_complet'],
                     json.dumps(before, ensure_ascii=False), json.dumps(data, ensure_ascii=False), version, int(time.time())))
                revision_id = cur.lastrowid
                summary = '; '.join(f'{k}: {before.get(k) if before else "—"} → {data[k] if data[k] is not None else "—"}' for k in SCORE_FIELDS)
                db.execute('INSERT INTO change_log(user_id,action,eleve_id,subject_id,details,created_at) VALUES (?,?,?,?,?,?)',
                    (user_id, 'update_notes', student_id, subject_id, f'T{trim} · {year} · {summary}', int(time.time())))
            results.append(dict(id=student_id, version=version, status=state, average=average, remark=remark, revision_id=revision_id))
        db.commit()
        return results
    except Exception:
        db.rollback()
        raise


def undo_revision(db, user_id, revision_id, scope):
    db.commit()
    try:
        db.execute('BEGIN IMMEDIATE')
        revision = db.execute('SELECT * FROM grade_revisions WHERE id=? AND user_id=? AND undone=0', (revision_id, user_id)).fetchone()
        if not revision:
            raise GradeError('forbidden')
        allowed_student(db, user_id, revision['eleve_id'], revision['school_year'], scope, revision['subject_id'])
        current = db.execute('SELECT * FROM notes WHERE user_id=? AND eleve_id=? AND subject_id=? AND trimestre=?',
            (user_id, revision['eleve_id'], revision['subject_id'], revision['trimestre'])).fetchone()
        if not current or current['version'] != revision['after_version'] or snapshot(current) != json.loads(revision['after_json']):
            raise GradeError('conflict', revision['eleve_id'])
        before = json.loads(revision['before_json'])
        if before is None:
            # Keep a tombstone version so an editor opened before undo cannot overwrite it.
            student = db.execute('SELECT * FROM eleves WHERE id=?', (revision['eleve_id'],)).fetchone()
            before = {key: None for key in NOTE_FIELDS}
            before.update({key: student[f'{key}_t{revision["trimestre"]}'] for key in SCORE_FIELDS})
            before.update(assessment_status='legacy', remarques=student[f'remarques_t{revision["trimestre"]}'] or '')
        write_note(db, user_id, revision['eleve_id'], revision['subject_id'], revision['trimestre'], before, current['version'] + 1)
        db.execute('UPDATE grade_revisions SET undone=1 WHERE id=?', (revision_id,))
        db.execute('INSERT INTO change_log(user_id,action,eleve_id,subject_id,details,created_at) VALUES (?,?,?,?,?,?)',
            (user_id, 'undo_notes', revision['eleve_id'], revision['subject_id'], f'T{revision["trimestre"]} · {revision["school_year"]}', int(time.time())))
        db.commit()
    except Exception:
        db.rollback()
        raise


def import_assessment(db, user_id, student_id, subject_id, trim, values, remark=None, components=None):
    """Merge supplied import cells; empty cells do not erase existing marks."""
    expressions = note_expr(trim)
    effective = db.execute(f'''SELECT {expressions[0]} AS devoir, {expressions[1]} AS activite,
        {expressions[2]} AS compo FROM eleves e LEFT JOIN notes n ON n.eleve_id=e.id AND n.user_id=e.user_id
        AND n.subject_id=? AND n.trimestre=? WHERE e.id=? AND e.user_id=?''',
        (subject_id, int(trim), student_id, user_id)).fetchone()
    current = db.execute('SELECT * FROM notes WHERE user_id=? AND eleve_id=? AND subject_id=? AND trimestre=?',
        (user_id, student_id, subject_id, int(trim))).fetchone()
    supplied = any(values.get(k) is not None for k in SCORE_FIELDS)
    if current and not supplied:
        return
    merged = {k: values.get(k) if values.get(k) is not None else effective[k] for k in SCORE_FIELDS}
    state = assessment_state(**merged)
    average = ((merged['activite'] + merged['devoir']) / 2 + merged['compo'] * 2) / 3 if state == 'graded' else None
    rules = db.execute('SELECT * FROM appreciations WHERE user_id=? ORDER BY min_val', (user_id,)).fetchall()
    generated = next((r['message'] for r in rules if average is not None and r['min_val'] <= average <= r['max_val']), '')
    if components is None:
        components = split_activite_components(merged['activite']) if merged['activite'] is not None else (None,)*5
        if current and current['activite'] == merged['activite']:
            components = tuple(current[k] for k in COMPONENTS)
    data = dict(zip(COMPONENTS, components), **merged, assessment_status=state,
                remarques=(remark or generated) if state == 'graded' else '')
    before = snapshot(current)
    if before == data:
        return
    version = (current['version'] if current else 0) + 1
    write_note(db, user_id, student_id, subject_id, trim, data, version)
    student = db.execute('SELECT nom_complet,school_year FROM eleves WHERE id=?', (student_id,)).fetchone()
    db.execute('''INSERT INTO grade_revisions(user_id,eleve_id,subject_id,trimestre,school_year,
        student_name,before_json,after_json,after_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (user_id,student_id,subject_id,int(trim),student['school_year'],student['nom_complet'],
         json.dumps(before,ensure_ascii=False),json.dumps(data,ensure_ascii=False),version,int(time.time())))
