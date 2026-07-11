"""Tests for scheduled backup observability."""

from core import backup


def test_backup_status_round_trip(tmp_path, monkeypatch):
    status_file = tmp_path / "last_backup.json"
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(backup, "BACKUP_STATUS_FILE", str(status_file))

    archive = tmp_path / "backup_20260711_120000.zip"
    archive.write_bytes(b"backup")
    written = backup.record_backup_status(True, str(archive))

    assert written["success"] is True
    assert written["filename"] == archive.name
    assert written["size_bytes"] == 6
    assert backup.get_backup_status() == written


def test_invalid_backup_status_is_ignored(tmp_path, monkeypatch):
    status_file = tmp_path / "last_backup.json"
    status_file.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(backup, "BACKUP_STATUS_FILE", str(status_file))

    assert backup.get_backup_status() is None
