"""The first dashboard of a newly imported teacher must support missing grades."""
from core.db import get_db


def test_new_teacher_dashboard_shows_116_ungraded_students_and_real_zero(auth_client, app):
    classes = {"1M1": 31, "1M2": 31, "2M1": 28, "2M2": 26}
    with app.app_context():
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE username='testprof'").fetchone()["id"]
        subject = db.execute("SELECT id FROM subjects WHERE user_id=?", (user,)).fetchone()["id"]
        for year in ("2025/2026", "2026/2027"):
            db.execute("INSERT OR IGNORE INTO school_years (label,is_active) VALUES (?,0)", (year,))
        db.execute("UPDATE school_years SET is_active=(label='2025/2026')")
        first = None
        for class_name, count in classes.items():
            db.execute("INSERT INTO teacher_assignments (user_id,school_year,subject_id,class_name) VALUES (?,'2026/2027',?,?)", (user,subject,class_name))
            for number in range(1,count+1):
                student = db.execute("INSERT INTO eleves (user_id,school_year,nom_complet,niveau) VALUES (?,'2026/2027',?,?)", (user,f"Eleve {class_name} {number:02d}",class_name)).lastrowid
                if first is None:
                    first = student
        db.commit()
    response = auth_client.get('/?per_page=200')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert page.count('data-grade-row') == 116
    assert 'None' not in page
    assert '2026/2027' in page
    assert '0 / 116' in page
    assert 'Non saisi' in page
    for class_name in classes:
        assert f'Eleve {class_name} 01' in page
    saved = auth_client.post('/sauvegarder_tout',json={"school_year":"2026/2027","subject":subject,"trimestre_save":"1","rows":[{"id":first,"activite":0,"devoir":0,"compo":0,"version":-1,"status":"auto"}]},headers={"X-CSRF-Token":"test-csrf"})
    assert saved.status_code == 200
    assert saved.get_json()["saved"][0]["status"] == "graded"
    assert saved.get_json()["saved"][0]["average"] == 0
    response = auth_client.get('/?per_page=200')
    assert response.status_code == 200
    assert '1 / 116' in response.get_data(as_text=True)