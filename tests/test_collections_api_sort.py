"""Tests for the order=asc|desc query param on GET /api/v1/collections.

These exercise the full HTTP path: client -> list_collections, asserting the
returned items are ordered according to the `order` query param (or each
sort field's existing default direction when `order` is absent / illegal).

Collection.name is UNIQUE, so the three seeded collections use distinct names.
Collection.updated_at only has `onupdate=` (which fires on UPDATE, not INSERT),
so explicit values persist on insert and let us control ordering deterministically.
"""

from datetime import datetime

import pytest


@pytest.fixture()
def seeded_collections(make_collection):
    """Three collections with distinct, controlled sort-field values."""
    alpha = make_collection(
        name="Alpha",
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    bravo = make_collection(
        name="Bravo",
        created_at=datetime(2024, 2, 1, 0, 0, 0),
        updated_at=datetime(2024, 2, 1, 0, 0, 0),
    )
    charlie = make_collection(
        name="Charlie",
        created_at=datetime(2024, 3, 1, 0, 0, 0),
        updated_at=datetime(2024, 3, 1, 0, 0, 0),
    )
    return {"alpha": alpha, "bravo": bravo, "charlie": charlie}


def _item_names(resp):
    """Extract the ordered list of collection names from a list_collections response.

    Response shape (see app/api/utils.py): success_response wraps
    paginate_response, so items live under body['data']['items'].
    """
    body = resp.get_json()
    assert body is not None, "response body was not JSON"
    assert body["code"] == 0, f"unexpected error code: {body}"
    items = body["data"]["items"]
    return [it["name"] for it in items]


def test_sort_updated_no_order_defaults_to_desc(client, seeded_collections):
    # updated_at default direction is desc -> latest (Charlie) first.
    resp = client.get("/api/v1/collections?sort=updated")
    assert _item_names(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_updated_order_asc_oldest_first(client, seeded_collections):
    resp = client.get("/api/v1/collections?sort=updated&order=asc")
    assert _item_names(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_name_order_desc_z_to_a(client, seeded_collections):
    # name default asc, flipped to desc -> Z->A.
    resp = client.get("/api/v1/collections?sort=name&order=desc")
    assert _item_names(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_name_no_order_defaults_to_asc(client, seeded_collections):
    # name default direction is asc -> A->Z.
    resp = client.get("/api/v1/collections?sort=name")
    assert _item_names(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_updated_illegal_order_falls_back_to_desc(client, seeded_collections):
    # Illegal order must fall back to the field's default (desc for updated).
    resp = client.get("/api/v1/collections?sort=updated&order=ILLEGAL")
    assert _item_names(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_updated_uppercase_order_asc(client, seeded_collections):
    # order is case-insensitive -> ASC behaves as asc.
    resp = client.get("/api/v1/collections?sort=updated&order=ASC")
    assert _item_names(resp) == ["Alpha", "Bravo", "Charlie"]
