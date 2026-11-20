"""
Creates all tables (if missing) and syncs the `characters` id registry with
the content files in backend/content/. The server already does this on every
start (app.ensure_db_ready), so running it by hand is rarely needed -- e.g. to
prepare a database before the first start, or as a deploy release step.

It only touches the `characters` table and never deletes rows (a character
removed from content stays registered, because accounts may reference it).
Accounts, stats and match history are never modified.

Run with: python seed_db.py
"""
from app import app, sync_character_registry, CATALOG
from models import db


def seed():
    with app.app_context():
        db.create_all()
        added, updated = sync_character_registry()
        print(f"Character registry synced: {len(CATALOG)} active, {added} added, {updated} updated.")


if __name__ == '__main__':
    seed()
