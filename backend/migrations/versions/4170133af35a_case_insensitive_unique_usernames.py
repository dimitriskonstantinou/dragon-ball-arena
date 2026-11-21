"""case-insensitive unique usernames (SEC-5)

Adds users.username_key = lower(username) with a unique index, so "Goku" and
"goku" can't both exist and login works with any capitalization.

Existing accounts are filled in from their current name. If the database already
holds names that differ only in capitalization, the upgrade stops with the list
(nothing is changed) -- renaming a player is a human decision, not a migration's.

Revision ID: 4170133af35a
Revises: 4d7e92ca43bc
Create Date: 2026-11-21 13:29:13.849563

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4170133af35a'
down_revision = '4d7e92ca43bc'
branch_labels = None
depends_on = None


def upgrade():
    # Keys are computed in Python, exactly like User.key_for() (SQL lower() differs
    # between databases for non-ASCII letters).
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, username FROM users")).fetchall()
    by_key = {}
    for user_id, username in users:
        by_key.setdefault(username.lower(), []).append(username)
    clashes = sorted(names for names in by_key.values() if len(names) > 1)
    if clashes:
        raise RuntimeError(
            "Cannot make usernames case-insensitive: these names differ only in capitalization: "
            + "; ".join(", ".join(repr(n) for n in sorted(names)) for names in clashes)
            + ". Rename all but one of each, then start again.")

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('username_key', sa.String(length=20), nullable=True))
    for user_id, username in users:
        conn.execute(sa.text("UPDATE users SET username_key = :key WHERE id = :id"),
                     {'key': username.lower(), 'id': user_id})
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('username_key', existing_type=sa.String(length=20), nullable=False)
        batch_op.create_index(batch_op.f('ix_users_username_key'), ['username_key'], unique=True)


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username_key'))
        batch_op.drop_column('username_key')
