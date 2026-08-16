"""
Creates all tables (if missing) and loads/refreshes the `characters` table
from the legacy characters.py roster. Safe to re-run -- it upserts by id,
so re-running after you edit characters.py picks up the changes.

Run with: python seed_db.py
"""
import json

from app import app
from models import db, Character
import characters as legacy_characters


def seed():
    with app.app_context():
        db.create_all()

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

        db.session.commit()
        print(f"Seeded {len(legacy_characters.CHARACTERS)} characters into the database.")


if __name__ == '__main__':
    seed()
