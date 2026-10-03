"""Helpers for tests that look into a view whose sections sit inside (nested) tabs."""


def all_sections(sections):
    """Every section of a view, depth first, with the sections inside tabs (and sub-tabs) included."""
    for section in sections:
        yield section
        for tab in section.get("tabs") or []:
            yield from all_sections(tab["sections"])


def section(view_or_sections, title=None, **match):
    sections = view_or_sections["sections"] if isinstance(view_or_sections, dict) else view_or_sections
    return next(s for s in all_sections(sections)
                if (title is None or s.get("title") == title) and all(s.get(k) == v for k, v in match.items()))
