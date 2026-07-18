"""Fælles hjælpefunktioner for entiteterne."""
from __future__ import annotations


def filter_by_categories(
    entries: list[dict], selected: list[str] | None
) -> list[dict]:
    """Behold kun poster hvis kategori er valgt. Tom liste = alt beholdes."""
    if not selected:
        return entries
    wanted = set(selected)
    return [e for e in entries if wanted.intersection(e.get("categories", []))]
