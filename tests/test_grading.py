"""Unit tests for edumaster.services.grading module."""
from edumaster.services.grading import (
    clean_component,
    note_expr,
    parse_float,
    safe_list_get,
    split_activite_components,
    sum_activite_components,
    trim_columns,
    validated_trim,
)
from core.utils import clean_note
import pytest


class TestCleanNote:
    def test_zero_for_empty(self):
        assert clean_note("") == 0.0
        assert clean_note(None) == 0.0

    def test_normal_value(self):
        assert clean_note("12.5") == 12.5

    def test_comma_separator(self):
        assert clean_note("14,5") == 14.5

    def test_cap_at_20(self):
        assert clean_note("25") == 20.0

    def test_negative_returns_zero(self):
        assert clean_note("-5") == 0.0

    def test_nan_returns_zero(self):
        assert clean_note("nan") == 0.0


class TestValidatedTrim:
    def test_valid(self):
        assert validated_trim("1") == "1"
        assert validated_trim("2") == "2"
        assert validated_trim("3") == "3"

    def test_default(self):
        assert validated_trim(None) == "1"
        assert validated_trim("") == "1"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            validated_trim("4")
        with pytest.raises(ValueError):
            validated_trim("abc")


class TestTrimColumns:
    def test_returns_mapping(self):
        cols = trim_columns("1")
        assert cols["devoir"] == "devoir_t1"
        assert cols["compo"] == "compo_t1"

    def test_trim_2(self):
        cols = trim_columns("2")
        assert cols["activite"] == "activite_t2"


class TestCleanComponent:
    def test_normal(self):
        assert clean_component("2.5", 3) == 2.5

    def test_over_max(self):
        assert clean_component("10", 3) == 3.0

    def test_empty(self):
        assert clean_component("", 5) == 0.0


class TestSumActiviteComponents:
    def test_sum(self):
        result = sum_activite_components(3, 6, 5, 4, 2)
        assert result == 20.0

    def test_zeros(self):
        result = sum_activite_components(0, 0, 0, 0, 0)
        assert result == 0.0


class TestSplitActiviteComponents:
    def test_full_20(self):
        p, b, k, pr, ao = split_activite_components(20)
        assert p == 3.0
        assert b == 6.0
        assert k == 5.0
        assert pr == 4.0
        assert ao == 2.0

    def test_partial(self):
        p, b, k, pr, ao = split_activite_components(5)
        assert p == 3.0
        assert b == 2.0
        assert k == 0.0

    def test_zero(self):
        p, b, k, pr, ao = split_activite_components(0)
        assert p == 0.0
        assert b == 0.0


class TestNoteExpr:
    def test_returns_five_values(self):
        result = note_expr("1")
        assert len(result) == 5

    def test_contains_safe_columns(self):
        devoir, _, _, _, _ = note_expr("2")
        assert "devoir_t2" in devoir
        assert "devoir_t{" not in devoir

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            note_expr("4")


class TestSafeListGet:
    def test_in_range(self):
        assert safe_list_get([1, 2, 3], 1) == 2

    def test_out_of_range(self):
        assert safe_list_get([1], 5, "default") == "default"


class TestParseFloat:
    def test_valid(self):
        assert parse_float("3.14") == 3.14

    def test_none(self):
        assert parse_float(None) is None

    def test_empty(self):
        assert parse_float("") is None
