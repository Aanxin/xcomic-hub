"""Shared sort-direction helpers.

Used by the comic/collection/history list endpoints to translate an inbound
`order` query parameter into a normalized direction and then into a
SQLAlchemy order-by clause. Kept dependency-free so it can be reused across
services without pulling in app config.
"""

ASC = 'asc'
DESC = 'desc'


def resolve_direction(order, default_direction):
    """Return 'asc' or 'desc'.

    If `order` (case-insensitive) is 'asc' or 'desc', use it; otherwise
    (None, '', illegal) fall back to `default_direction` for backward
    compatibility.
    """
    if isinstance(order, str):
        lowered = order.lower()
        if lowered == ASC:
            return ASC
        if lowered == DESC:
            return DESC
    return default_direction


def apply_order(column, direction):
    """Return ``column.desc()`` if ``direction == 'desc'`` else ``column.asc()``."""
    if direction == DESC:
        return column.desc()
    return column.asc()
