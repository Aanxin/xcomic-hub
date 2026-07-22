"""Tests for the order=asc|desc query param on GET / (main.index).

These exercise the full server-rendered HTML path: client -> index() ->
sort_map / resolve_direction / apply_order, asserting the rendered comic
cards appear in document order according to the `order` query param (or
each sort field's existing default direction when `order` is absent /
illegal / uppercase).

Only standalone comics (no collection_id) are seeded, so every card title
in the rendered HTML belongs to a comic card — there is no ambiguity with
collection card titles (which use the same `card-title` class).
"""

import re
from datetime import datetime

import pytest


@pytest.fixture()
def seeded_comics(make_comic):
    """Three standalone comics with distinct, controlled sort-field values.

    updated_at / created_at are set explicitly. Because Comic.updated_at only
    has `onupdate=` (which fires on UPDATE, not INSERT), the explicit values
    persist on insert and let us control ordering deterministically.
    """
    alpha = make_comic(
        title="Alpha",
        file_size=100,
        rating=2.0,
        created_at=datetime(2024, 1, 1, 0, 0, 0),
        updated_at=datetime(2024, 1, 1, 0, 0, 0),
    )
    bravo = make_comic(
        title="Bravo",
        file_size=200,
        rating=3.0,
        created_at=datetime(2024, 2, 1, 0, 0, 0),
        updated_at=datetime(2024, 2, 1, 0, 0, 0),
    )
    charlie = make_comic(
        title="Charlie",
        file_size=300,
        rating=1.0,
        created_at=datetime(2024, 3, 1, 0, 0, 0),
        updated_at=datetime(2024, 3, 1, 0, 0, 0),
    )
    return {"alpha": alpha, "bravo": bravo, "charlie": charlie}


_CARD_TITLE_RE = re.compile(
    r'<h5 class="card-title text-truncate">(.*?)</h5>', re.DOTALL
)


def _comic_titles_in_order(resp):
    """Extract comic card titles from the rendered HTML in document order.

    The comic card markup (app/templates/index.html) renders each title as
    `<h5 class="card-title text-truncate">{{ comic.title }}</h5>`. Because the
    fixture seeds NO collections, every such element is a comic title, so
    collecting them in document order yields the comic sort order.
    """
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200, f"unexpected status: {resp.status_code}"
    titles = _CARD_TITLE_RE.findall(html)
    assert titles, "no card-title elements found in rendered HTML"
    return titles


def test_sort_updated_no_order_defaults_to_desc(client, seeded_comics):
    # updated_at default direction is desc -> latest (Charlie) first.
    resp = client.get("/?sort=updated")
    assert _comic_titles_in_order(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_updated_order_asc_oldest_first(client, seeded_comics):
    resp = client.get("/?sort=updated&order=asc")
    assert _comic_titles_in_order(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_title_order_desc_z_to_a(client, seeded_comics):
    # title default asc, flipped to desc -> Z->A.
    resp = client.get("/?sort=title&order=desc")
    assert _comic_titles_in_order(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_title_no_order_defaults_to_asc(client, seeded_comics):
    # title default direction is asc -> A->Z.
    resp = client.get("/?sort=title")
    assert _comic_titles_in_order(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_size_order_asc_ascending(client, seeded_comics):
    # size default desc, flipped to asc -> smallest first.
    resp = client.get("/?sort=size&order=asc")
    assert _comic_titles_in_order(resp) == ["Alpha", "Bravo", "Charlie"]


def test_sort_size_no_order_defaults_to_desc(client, seeded_comics):
    # size default direction is desc -> largest (Charlie) first.
    resp = client.get("/?sort=size")
    assert _comic_titles_in_order(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_rating_no_order_defaults_to_desc(client, seeded_comics):
    # rating default direction is desc -> highest (Bravo=3.0) first.
    resp = client.get("/?sort=rating")
    assert _comic_titles_in_order(resp) == ["Bravo", "Alpha", "Charlie"]


def test_sort_rating_order_asc_lowest_first(client, seeded_comics):
    resp = client.get("/?sort=rating&order=asc")
    assert _comic_titles_in_order(resp) == ["Charlie", "Alpha", "Bravo"]


def test_sort_updated_illegal_order_falls_back_to_desc(client, seeded_comics):
    # Illegal order must fall back to the field's default (desc for updated).
    resp = client.get("/?sort=updated&order=ILLEGAL")
    assert _comic_titles_in_order(resp) == ["Charlie", "Bravo", "Alpha"]


def test_sort_updated_uppercase_order_asc(client, seeded_comics):
    # order is case-insensitive -> ASC behaves as asc.
    resp = client.get("/?sort=updated&order=ASC")
    assert _comic_titles_in_order(resp) == ["Alpha", "Bravo", "Charlie"]


# ---------------------------------------------------------------------------
# Task 5: sort-direction toggle button + order threading + localStorage
# (rendered-HTML assertions). The route passes order=effective_order to the
# template, where effective_order is always 'asc' or 'desc'.
# ---------------------------------------------------------------------------

_ANCHOR_RE = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.DOTALL)


def _find_toggle(html):
    """Return (attrs, inner_html) for the <a> with id="sort-order-toggle".

    Returns (None, None) if the toggle is absent. Attribute order in the
    opening tag is not guaranteed, so we scan all anchors.
    """
    for m in _ANCHOR_RE.finditer(html):
        attrs, inner = m.group(1), m.group(2)
        if 'id="sort-order-toggle"' in attrs:
            return attrs, inner
    return None, None


def _href(attrs):
    m = re.search(r'href="([^"]*)"', attrs)
    return m.group(1) if m else None


def test_toggle_present_and_flips_desc_to_asc(client, seeded_comics):
    # sort=updated with no order -> effective desc -> toggle offers asc, icon down.
    html = client.get("/?sort=updated").data.decode("utf-8")
    attrs, inner = _find_toggle(html)
    assert attrs is not None, "sort-order-toggle element missing from rendered HTML"
    href = _href(attrs)
    assert href is not None, "sort-order-toggle anchor has no href"
    assert "order=asc" in href
    assert "bi-sort-down" in inner


def test_toggle_flips_asc_to_desc_and_shows_up_icon(client, seeded_comics):
    # sort=updated&order=asc -> effective asc -> toggle offers desc, icon up.
    html = client.get("/?sort=updated&order=asc").data.decode("utf-8")
    attrs, inner = _find_toggle(html)
    assert attrs is not None, "sort-order-toggle element missing from rendered HTML"
    href = _href(attrs)
    assert href is not None, "sort-order-toggle anchor has no href"
    assert "order=desc" in href
    assert "bi-sort-up" in inner


def test_toggle_for_title_default_asc(client, seeded_comics):
    # title default direction is asc -> toggle offers desc, icon up.
    html = client.get("/?sort=title").data.decode("utf-8")
    attrs, inner = _find_toggle(html)
    assert attrs is not None, "sort-order-toggle element missing from rendered HTML"
    href = _href(attrs)
    assert href is not None, "sort-order-toggle anchor has no href"
    assert "order=desc" in href
    assert "bi-sort-up" in inner


def test_sort_dropdown_threads_current_order(client, seeded_comics):
    # Switching sort field must carry the current order through the dropdown
    # item hrefs (design 6.1: direction is independent of field).
    html = client.get("/?sort=updated&order=asc").data.decode("utf-8")
    title_href = None
    for m in _ANCHOR_RE.finditer(html):
        attrs = m.group(1)
        if 'dropdown-item' in attrs:
            href = _href(attrs)
            if href and 'sort=title' in href:
                title_href = href
                break
    assert title_href is not None, "sort=title dropdown item not found in rendered HTML"
    assert "order=asc" in title_href


def test_localstorage_persists_order(client, seeded_comics):
    # The persistence script must wire library_order alongside library_sort.
    html = client.get("/?sort=updated&order=asc").data.decode("utf-8")
    assert "library_order" in html
