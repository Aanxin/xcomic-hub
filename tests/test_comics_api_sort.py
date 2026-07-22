"""Tests for the order=asc|desc query param on GET /api/v1/comics.

These exercise the full HTTP path: client -> list_comics ->
ComicQueryService.build_comic_query -> _apply_sort, asserting the returned
items are ordered according to the `order` query param (or the field's
existing default direction when `order` is absent / illegal).
"""

from datetime import datetime

import pytest


@pytest.fixture()
def seeded_comics(make_comic):
    """Three comics with distinct, controlled sort-field values.

    updated_at / created_at are set explicitly. Because Comic.updated_at only
    has `onupdate=` (which fires on UPDATE, not INSERT), the explicit values
    persist on insert and let us control ordering deterministically.
    """
    alpha = make_comic(
        title="Alpha",
        rating=1.0,
        file_size=100,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    bravo = make_comic(
        title="Bravo",
        rating=2.0,
        file_size=200,
        created_at=datetime(2024, 2, 1, 0, 0, 0),
        updated_at=datetime(2024, 2, 1, 0, 0, 0),
    )
    charlie = make_comic(
        title="Charlie",
        rating=3.0,
        file_size=300,
        created_at=datetime(2024, 3, 1, 0, 0, 0),
        updated_at=datetime(2024, 3, 1, 0, 0, 0),
    )
    return {"alpha": alpha, "bravo": bravo, "charlie": charlie}


def _item_titles(resp):
    """Extract the ordered list of comic titles from a list_comics response.

    Response shape (see app/api/utils.py): success_response wraps
    paginate_response, so items live under body['data']['items'].
    """
    body = resp.get_json()
    assert body is not None, "response body was not JSON"
    assert body["code"] == 0, f"unexpected error code: {body}"
    items = body["data"]["items"]
    return [it["title"] for it in items]


def test_sort_updated_no_order_defaults_to_desc(client, seeded_comics):
    # updated_at default direction is desc -> latest (Charlie) first.
    resp = client.get("/api/v1/comics?sort=updated")
    assert _item_titles(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_updated_order_asc_oldest_first(client, seeded_comics):
    resp = client.get("/api/v1/comics?sort=updated&order=asc")
    assert _item_titles(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_title_order_desc_z_to_a(client, seeded_comics):
    # title default asc, flipped to desc -> Z->A.
    resp = client.get("/api/v1/comics?sort=title&order=desc")
    assert _item_titles(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_title_no_order_defaults_to_asc(client, seeded_comics):
    # title default direction is asc -> A->Z.
    resp = client.get("/api/v1/comics?sort=title")
    assert _item_titles(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_rating_order_asc_ascending(client, seeded_comics):
    resp = client.get("/api/v1/comics?sort=rating&order=asc")
    assert _item_titles(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_updated_illegal_order_falls_back_to_desc(client, seeded_comics):
    # Illegal order must fall back to the field's default (desc for updated).
    resp = client.get("/api/v1/comics?sort=updated&order=ILLEGAL")
    assert _item_titles(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_updated_uppercase_order_asc(client, seeded_comics):
    # order is case-insensitive -> ASC behaves as asc.
    resp = client.get("/api/v1/comics?sort=updated&order=ASC")
    assert _item_titles(resp) == ["Alpha", "Bravo", "Charlie"]
