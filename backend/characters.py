"""
The character roster, loaded from backend/content/ (the single source of
truth -- edit the JSON files there, not this module).

Kept as a thin compatibility layer so app.py, seed_db.py, the tests and the
tools keep importing `characters.CHARACTERS` unchanged. Invalid content
raises content_loader.ContentError here, i.e. at server start.
"""
from content_loader import load_catalog

CHARACTERS = load_catalog()
