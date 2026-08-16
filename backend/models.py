"""
Database models (SQLAlchemy / Flask-SQLAlchemy).

Local dev uses SQLite (zero setup); production should point DATABASE_URL at
a real Postgres instance instead -- SQLAlchemy makes that a connection
string change, not a rewrite. See README for why SQLite specifically must
not be used in production on most hosts (ephemeral disk).
"""
import json
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    stats = db.relationship('UserStats', backref='user', uselist=False, cascade='all, delete-orphan')
    unlocked_characters = db.relationship('UserCharacter', backref='user', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'stats': self.stats.to_dict() if self.stats else None,
        }


class UserStats(db.Model):
    __tablename__ = 'user_stats'

    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), primary_key=True)
    total_matches = db.Column(db.Integer, default=0, nullable=False)
    total_wins = db.Column(db.Integer, default=0, nullable=False)
    total_losses = db.Column(db.Integer, default=0, nullable=False)
    current_win_streak = db.Column(db.Integer, default=0, nullable=False)
    longest_win_streak = db.Column(db.Integer, default=0, nullable=False)
    current_loss_streak = db.Column(db.Integer, default=0, nullable=False)
    last_match_at = db.Column(db.DateTime, nullable=True)

    def record_result(self, won):
        self.total_matches += 1
        if won:
            self.total_wins += 1
            self.current_win_streak += 1
            self.current_loss_streak = 0
            if self.current_win_streak > self.longest_win_streak:
                self.longest_win_streak = self.current_win_streak
        else:
            self.total_losses += 1
            self.current_loss_streak += 1
            self.current_win_streak = 0
        self.last_match_at = utcnow()

    def to_dict(self):
        return {
            'total_matches': self.total_matches,
            'total_wins': self.total_wins,
            'total_losses': self.total_losses,
            'current_win_streak': self.current_win_streak,
            'longest_win_streak': self.longest_win_streak,
            'current_loss_streak': self.current_loss_streak,
            'win_rate': round(self.total_wins / self.total_matches, 4) if self.total_matches else 0.0,
        }


class Character(db.Model):
    """The master roster. This replaces characters.py's CHARACTERS dict as
    the source of truth once the DB is seeded (see seed_db.py) -- the game
    engine itself doesn't care where a character dict came from."""
    __tablename__ = 'characters'

    id = db.Column(db.String(32), primary_key=True)  # e.g. "goku"
    name = db.Column(db.String(64), nullable=False)
    image = db.Column(db.String(128), nullable=False)  # filename under /photos, e.g. "Goku.png"
    health = db.Column(db.Integer, nullable=False, default=100)
    skills_json = db.Column(db.Text, nullable=False)  # JSON-encoded list of skill dicts
    # Not used for gating yet (every account currently gets every character --
    # see the TODO in app.py's register route). Kept so the mission-unlock
    # system has a flag to switch on later without a schema change.
    is_starter = db.Column(db.Boolean, default=False, nullable=False)

    def skills(self):
        return json.loads(self.skills_json)

    def to_game_dict(self):
        """Shape expected by game_engine.py / the frontend."""
        return {
            'id': self.id, 'name': self.name, 'image': self.image,
            'health': self.health, 'maxHealth': self.health,
            'defense': 0, 'status': [],
            'skills': self.skills(),
        }


class UserCharacter(db.Model):
    """Join table: which characters a given account has unlocked."""
    __tablename__ = 'user_characters'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    character_id = db.Column(db.String(32), db.ForeignKey('characters.id'), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'character_id', name='uq_user_character'),)


class Mission(db.Model):
    """Schema groundwork for mission-based unlocks -- not populated or wired
    up to gameplay yet. See README for the auto-tracked vs. manual design
    question that needs answering before this becomes real."""
    __tablename__ = 'missions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.String(255))
    requirement = db.Column(db.String(255))  # human-readable for now
    reward_character_id = db.Column(db.String(32), db.ForeignKey('characters.id'), nullable=True)


class UserMissionProgress(db.Model):
    __tablename__ = 'user_mission_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    mission_id = db.Column(db.Integer, db.ForeignKey('missions.id'), nullable=False)
    progress = db.Column(db.Integer, default=0, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('user_id', 'mission_id', name='uq_user_mission'),)


class Match(db.Model):
    __tablename__ = 'matches'

    id = db.Column(db.Integer, primary_key=True)
    player1_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    player2_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    winner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # null = disconnect/no result
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=False)
