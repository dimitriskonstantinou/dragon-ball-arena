"""no draws: drop matches.is_draw, user_stats.total_draws (ENG-2, user decision 2026-11-21)

Step 27 made a mutual KO a draw; the user then decided there are no draws: the
team wiped out first loses. These two columns can't hold anything but false / 0
(no draw was ever recorded outside tests), so dropping them loses nothing.

A new migration rather than deleting Step 27's: a local database that already
ran 399b42c2815d (e.g. the server started on that branch) must still find its
revision in the history.

Revision ID: aac3382b42ab
Revises: 399b42c2815d
Create Date: 2026-11-21 18:26:25.047000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'aac3382b42ab'
down_revision = '399b42c2815d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_stats', schema=None) as batch_op:
        batch_op.drop_column('total_draws')

    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.drop_column('is_draw')


def downgrade():
    # Same definitions as 399b42c2815d (sa.false() renders correctly on SQLite and PostgreSQL).
    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_draw', sa.Boolean(), server_default=sa.false(), nullable=False))

    with op.batch_alter_table('user_stats', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total_draws', sa.Integer(), server_default='0', nullable=False))
