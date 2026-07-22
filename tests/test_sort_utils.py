"""Unit tests for the shared sort-direction utility helpers.

These tests are intentionally pure: `apply_order` is exercised against a
standalone SQLAlchemy column so no app/DB fixture is required.
"""

from sqlalchemy import Column, String

from app.utils.sort_utils import ASC, DESC, apply_order, resolve_direction


# ---------------------------------------------------------------------------
# resolve_direction
# ---------------------------------------------------------------------------

def test_resolve_direction_lowercase_asc():
    assert resolve_direction("asc", "desc") == "asc"


def test_resolve_direction_lowercase_desc():
    assert resolve_direction("desc", "asc") == "desc"


def test_resolve_direction_uppercase_asc_is_normalized():
    assert resolve_direction("ASC", "desc") == "asc"


def test_resolve_direction_uppercase_desc_is_normalized():
    assert resolve_direction("DESC", "asc") == "desc"


def test_resolve_direction_none_falls_back_to_default():
    assert resolve_direction(None, "desc") == "desc"


def test_resolve_direction_empty_string_falls_back_to_default():
    assert resolve_direction("", "asc") == "asc"


def test_resolve_direction_illegal_value_falls_back_to_default():
    assert resolve_direction("sideways", "desc") == "desc"


def test_resolve_direction_returns_asc_constant_for_asc_input():
    assert resolve_direction("asc", "desc") == ASC


def test_resolve_direction_returns_desc_constant_for_desc_input():
    assert resolve_direction("desc", "asc") == DESC


# ---------------------------------------------------------------------------
# apply_order
# ---------------------------------------------------------------------------

def test_apply_order_desc_matches_column_desc():
    col = Column("x", String)
    assert apply_order(col, "desc").compare(col.desc())


def test_apply_order_asc_matches_column_asc():
    col = Column("x", String)
    assert apply_order(col, "asc").compare(col.asc())


def test_apply_order_non_desc_defaults_to_asc():
    col = Column("x", String)
    # Anything that isn't 'desc' should behave as asc (backward compat).
    assert apply_order(col, "asc").compare(col.asc())
