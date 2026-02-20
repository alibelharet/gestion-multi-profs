"""Unit tests for edumaster.services.common and core.security modules."""
from edumaster.services.common import parse_trim, school_year
from datetime import datetime


class TestParseTrim:
    def test_valid(self):
        assert parse_trim("1") == "1"
        assert parse_trim("2") == "2"
        assert parse_trim("3") == "3"

    def test_invalid_returns_default(self):
        assert parse_trim("4") == "1"
        assert parse_trim("abc") == "1"
        assert parse_trim(None) == "1"

    def test_custom_default(self):
        assert parse_trim("bad", default="2") == "2"


class TestSchoolYear:
    def test_september_onward(self):
        dt = datetime(2025, 9, 15)
        assert school_year(dt) == "2025/2026"

    def test_before_september(self):
        dt = datetime(2026, 3, 1)
        assert school_year(dt) == "2025/2026"

    def test_january(self):
        dt = datetime(2026, 1, 1)
        assert school_year(dt) == "2025/2026"
