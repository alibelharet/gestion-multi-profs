"""Regression coverage for real zeros, missing values, atomic saving and recovery."""
import json
from io import BytesIO
import pytest
from openpyxl import load_workbook
from core.db import get_db
from edumaster.services.dashboard_service import compute_stats_summary
from edumaster.services.grade_editor import import_assessment


@pytest.fixture
def classroom(auth_client, app):
    with app.app_context():
        db=get_db()
        user=db.execute("SELECT id FROM users WHERE username='testprof'").fetchone()['id']
        subject=db.execute('SELECT id FROM subjects WHERE user_id=?',(user,)).fetchone()['id']
        year=db.execute('SELECT label FROM school_years WHERE is_active=1').fetchone()['label']
        ids=[]
        for name in ['Élève Démo A','Élève Démo B','Élève Démo C']:
            ids.append(db.execute('INSERT INTO eleves(user_id,school_year,nom_complet,niveau) VALUES (?,?,?,?)',
                                  (user,year,name,'2M1')).lastrowid)
        db.commit()
    return dict(user=user,subject=subject,year=year,ids=ids)


def send(client, c, rows):
    return client.post('/sauvegarder_tout',json=dict(school_year=c['year'],subject=c['subject'],trimestre_save='1',rows=rows),headers={'X-CSRF-Token':'test-csrf'})


def marks(student, a='', d='', c='', version=-1, status='auto'):
    return dict(id=student,activite=a,devoir=d,compo=c,version=version,status=status)


def test_missing_zero_absent_and_complete_have_distinct_statistics(auth_client,app,classroom):
    c=classroom
    response=send(auth_client,c,[marks(c['ids'][0],0,0,0),marks(c['ids'][1],15,15,15),marks(c['ids'][2],18,18,18,status='absent')])
    assert response.status_code==200, response.get_data(as_text=True)
    with app.app_context():
        stats=compute_stats_summary(get_db(),c['user'],'1',c['subject'],'e.user_id=?',[c['user']])
        assert stats['nb_total']==3
        assert stats['nb_saisis']==2
        assert stats['moyenne_generale']==7.5
        assert stats['taux_reussite']==50
    response=auth_client.get('/')
    assert response.status_code==200
    assert 'None' not in response.get_data(as_text=True)


def test_partial_scores_remain_empty_and_have_no_appreciation(auth_client,app,classroom):
    c=classroom
    response=send(auth_client,c,[marks(c['ids'][0],15,'','')])
    assert response.status_code==200
    saved=response.get_json()['saved'][0]
    assert saved['status']=='partial' and saved['average'] is None and saved['remark']==''
    with app.app_context():
        row=get_db().execute('SELECT * FROM notes WHERE eleve_id=?',(c['ids'][0],)).fetchone()
        assert row['devoir'] is None and row['compo'] is None
    assert auth_client.get('/').status_code==200


def test_legacy_zeros_are_preserved_and_flagged(auth_client,app,classroom):
    c=classroom
    with app.app_context():
        db=get_db();db.execute('INSERT INTO notes(user_id,eleve_id,subject_id,trimestre,activite,devoir,compo) VALUES (?,?,?,1,0,0,0)',
                               (c['user'],c['ids'][0],c['subject']));db.commit()
    response=auth_client.get('/')
    assert 'Ancien zéro à vérifier' in response.get_data(as_text=True)
    with app.app_context():
        row=get_db().execute('SELECT activite,devoir,compo,assessment_status FROM notes').fetchone()
        assert tuple(row)==(0,0,0,'legacy')


@pytest.mark.parametrize('bad',[21,-1,'no','Infinity'])
def test_invalid_batch_is_atomic(auth_client,app,classroom,bad):
    c=classroom
    response=send(auth_client,c,[marks(c['ids'][0],10,10,10),marks(c['ids'][1],bad,12,12)])
    assert response.status_code==400
    with app.app_context():
        db=get_db()
        assert db.execute('SELECT count(*) FROM notes').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM grade_revisions').fetchone()[0]==0


def test_stale_editor_cannot_overwrite_saved_notes(auth_client,app,classroom):
    c=classroom
    assert send(auth_client,c,[marks(c['ids'][0],10,10,10)]).status_code==200
    response=send(auth_client,c,[marks(c['ids'][0],18,18,18)])
    assert response.status_code==409
    with app.app_context():
        assert get_db().execute('SELECT devoir FROM notes').fetchone()[0]==10


def test_foreign_student_aborts_whole_batch(auth_client,app,classroom):
    c=classroom
    with app.app_context():
        db=get_db()
        other=db.execute("INSERT INTO users(username,password,nom_affichage) VALUES ('another','hash','Autre')").lastrowid
        student=db.execute("INSERT INTO eleves(user_id,school_year,nom_complet,niveau) VALUES (?,?, 'Autre','2M1')",(other,c['year'])).lastrowid
        db.commit()
    response=send(auth_client,c,[marks(c['ids'][0],10,10,10),marks(student,11,11,11)])
    assert response.status_code==403
    with app.app_context():
        assert get_db().execute('SELECT count(*) FROM notes').fetchone()[0]==0


def test_import_preserves_empty_cells_and_explicit_zero(auth_client,app,classroom):
    c=classroom
    send(auth_client,c,[marks(c['ids'][0],10,10,10)])
    with app.app_context():
        db=get_db()
        import_assessment(db,c['user'],c['ids'][0],c['subject'],'1',dict(activite=None,devoir=0,compo=None))
        import_assessment(db,c['user'],c['ids'][1],c['subject'],'1',dict(activite=0,devoir=None,compo=None))
        db.commit()
        row=db.execute('SELECT activite,devoir,compo,assessment_status FROM notes WHERE eleve_id=?',(c['ids'][0],)).fetchone()
        assert tuple(row)==(10,0,10,'graded')
        row=db.execute('SELECT activite,devoir,compo,assessment_status FROM notes WHERE eleve_id=?',(c['ids'][1],)).fetchone()
        assert tuple(row)==(0,None,None,'partial')
    assert send(auth_client,c,[marks(c['ids'][0],15,15,15,version=1)]).status_code==409


def test_undo_restores_previous_values_and_cannot_repeat(auth_client,app,classroom):
    c=classroom
    first=send(auth_client,c,[marks(c['ids'][0],10,11,12)]).get_json()['saved'][0]
    second=send(auth_client,c,[marks(c['ids'][0],15,16,17,version=first['version'])]).get_json()['saved'][0]
    response=auth_client.post(f"/history/grades/{second['revision_id']}/undo",data={'csrf_token':'test-csrf'},follow_redirects=True)
    assert response.status_code==200
    with app.app_context():
        row=get_db().execute('SELECT activite,devoir,compo FROM notes').fetchone()
        assert tuple(row)==(10,11,12)
    response=auth_client.post(f"/history/grades/{second['revision_id']}/undo",data={'csrf_token':'test-csrf'})
    assert response.status_code==302


def test_trash_restores_student_and_all_notes(auth_client,app,classroom):
    c=classroom
    send(auth_client,c,[marks(c['ids'][0],10,11,12)])
    response=auth_client.post('/supprimer_multi',data={'ids':c['ids'][0],'school_year':c['year'],'csrf_token':'test-csrf'})
    assert response.status_code==302
    with app.app_context():
        db=get_db()
        assert not db.execute('SELECT 1 FROM eleves WHERE id=?',(c['ids'][0],)).fetchone()
        entry=db.execute('SELECT id FROM student_trash').fetchone()['id']
    assert auth_client.get('/trash').status_code==200
    response=auth_client.post(f'/trash/{entry}/restore',data={'csrf_token':'test-csrf'},follow_redirects=True)
    assert response.status_code==200
    with app.app_context():
        db=get_db()
        assert db.execute('SELECT count(*) FROM student_trash').fetchone()[0]==0
        assert db.execute('SELECT devoir FROM notes WHERE eleve_id=?',(c['ids'][0],)).fetchone()[0]==11


def test_exports_and_arabic_view_do_not_turn_missing_into_zero(auth_client,app,classroom):
    c=classroom
    send(auth_client,c,[marks(c['ids'][0],0,0,0),marks(c['ids'][1],15,'','')])
    response=auth_client.get('/export_excel')
    assert response.status_code==200
    sheet=load_workbook(BytesIO(response.data)).active
    values=list(sheet.values)
    header=list(values[0]);devoir=header.index('Devoir');moyenne=header.index('Moyenne')
    assert values[1][moyenne]==0
    assert values[2][devoir] is None and values[2][moyenne] is None
    auth_client.get('/lang/ar')
    html=auth_client.get('/').get_data(as_text=True)
    assert 'إدخال العلامات' in html and 'Bienvenue' not in html and 'user-scalable=no' not in html
    for path in ('/stats','/history','/history/grades','/trash','/print_list','/export_list_pdf','/export_stats_pdf'):
        response=auth_client.get(path)
        assert response.status_code==200, path


def test_all_templates_compile(app):
    for name in app.jinja_env.list_templates():
        app.jinja_env.get_template(name)


def test_import_keeps_supplied_activity_components(app, classroom):
    c = classroom
    with app.app_context():
        db = get_db()
        import_assessment(db, c['user'], c['ids'][0], c['subject'], '1',
                          dict(activite=10, devoir=12, compo=14), components=(1, 3, 2, 3, 1))
        db.commit()
        row = db.execute('SELECT participation,comportement,cahier,projet,assiduite_outils FROM notes').fetchone()
        assert tuple(row) == (1, 3, 2, 3, 1)
