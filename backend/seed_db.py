"""
Creates all tables (if missing) and syncs the `characters` table to match
characters.py exactly (upserts changed/new characters, deletes rows whose id
no longer exists in characters.py). Safe to re-run.

IMPORTANT: this only ever touches the `characters` table. It never deletes
or modifies `users`, `user_stats`, `user_characters`, or `matches` -- so
real accounts and their history always survive a re-seed. Never delete
game.db to "reset" character data; just re-run this script.

Run with: python seed_db.py
"""
import json

from app import app
from models import db, Character
import characters as legacy_characters


def seed():
    with app.app_context():
        db.create_all()

        current_ids = set(legacy_characters.CHARACTERS.keys())

        for char_id, char in legacy_characters.CHARACTERS.items():
            skills_json = json.dumps(char['skills'])
            row = db.session.get(Character, char_id)
            if row:
                row.name = char['name']
                row.image = char['image']
                row.health = char['health']
                row.skills_json = skills_json
            else:
                db.session.add(Character(
                    id=char_id, name=char['name'], image=char['image'],
                    health=char['health'], skills_json=skills_json, is_starter=True,
                ))

        removed = Character.query.filter(~Character.id.in_(current_ids)).all() if current_ids else Character.query.all()
        for row in removed:
            print(f"Removing '{row.id}' -- no longer in characters.py")
            db.session.delete(row)

        db.session.commit()
        print(f"Synced: {len(legacy_characters.CHARACTERS)} characters current, {len(removed)} removed.")


if __name__ == '__main__':
    seed()
