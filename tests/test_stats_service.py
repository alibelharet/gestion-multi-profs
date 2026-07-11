"""Tests for the statistics service."""


def _insert_grade(db, user_id, student_id, subject_id, trimester, value):
    db.execute(
        """
        INSERT INTO notes (
            user_id, eleve_id, subject_id, trimestre, activite, devoir, compo
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, student_id, subject_id, trimester, value, value, value),
    )


def test_declining_students_filters_small_drops_and_classes(app, db):
    from edumaster.services.stats_service import get_declining_students

    user_id = db.execute(
        """
        INSERT INTO users (username, password, nom_affichage)
        VALUES ('stats-prof', 'unused', 'Stats Prof')
        """
    ).lastrowid
    subject_id = db.execute(
        "INSERT INTO subjects (user_id, name) VALUES (?, ?)",
        (user_id, "Mathématiques"),
    ).lastrowid

    students = {}
    for name, level in (("Baisse forte", "3A"), ("Baisse légère", "3A"), ("Autre classe", "3B")):
        students[name] = db.execute(
            """
            INSERT INTO eleves (user_id, school_year, nom_complet, niveau)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, "2025-2026", name, level),
        ).lastrowid

    _insert_grade(db, user_id, students["Baisse forte"], subject_id, 1, 15)
    _insert_grade(db, user_id, students["Baisse forte"], subject_id, 2, 11)
    _insert_grade(db, user_id, students["Baisse légère"], subject_id, 1, 12)
    _insert_grade(db, user_id, students["Baisse légère"], subject_id, 2, 11.5)
    _insert_grade(db, user_id, students["Autre classe"], subject_id, 1, 16)
    _insert_grade(db, user_id, students["Autre classe"], subject_id, 2, 12)
    db.commit()

    result = get_declining_students(
        user_id,
        subject_id,
        "2025-2026",
        "2",
        allowed_classes={"3A"},
    )

    assert [student["nom"] for student in result] == ["Baisse forte"]
    assert result[0]["previous_average"] == 15.0
    assert result[0]["current_average"] == 11.0
    assert result[0]["delta"] == -4.0


def test_declining_students_returns_nothing_for_first_trimester(app, db):
    from edumaster.services.stats_service import get_declining_students

    assert get_declining_students(1, 1, "2025-2026", "1") == []
