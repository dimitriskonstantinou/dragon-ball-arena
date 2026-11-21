"""
Database migration tests (Flask-Migrate / Alembic, backend/migrations/).
Run with: python test_migrations.py

Every scenario runs in its own interpreter on its own temporary SQLite file
(the app binds its database at import), so the real backend/game.db is never
touched. The most important check: migrations and models describe exactly the
same schema -- it fails if a model changes without a migration.
"""
import os
import subprocess
import sys
import tempfile

FAILURES = []
BACKEND = os.path.dirname(os.path.abspath(__file__))

PRELUDE = '''
import sqlite3, sys
sys.path.insert(0, ".")
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
def schema_diff(appmod):
    with appmod.app.app_context():
        with appmod.db.engine.connect() as conn:
            return compare_metadata(MigrationContext.configure(conn), appmod.db.metadata)
def version(path):
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("select version_num from alembic_version")]
    finally:
        con.close()
'''

LEGACY_DB = '''
# A database exactly as the pre-Step-23 code made it: the baseline schema (applied
# from the baseline migration), no migration history, plus data written with plain SQL.
# (db.create_all() with today's models would NOT be faithful: they have newer columns.)
import os
from flask import Flask
from flask_migrate import Migrate, upgrade
from models import db
legacy = Flask("legacy")
legacy.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB
db.init_app(legacy)
Migrate(legacy, db, directory=os.path.join(".", "migrations"), render_as_batch=True)
with legacy.app_context():
    upgrade(directory=os.path.join(".", "migrations"), revision="def555b6f5cf")
con = sqlite3.connect(DB)
con.execute("drop table alembic_version")
con.execute("insert into users (id, username, email, password_hash, created_at) "
            "values (1, 'old_player', 'old@x.io', 'hash-kept', '2026-08-16 20:00:00')")
con.execute("insert into users (id, username, email, password_hash, created_at) "
            "values (2, 'Old_Vegeta', 'veg@x.io', 'hash-2', '2026-08-17 20:00:00')")
con.execute("insert into user_stats (user_id, total_matches, total_wins, total_losses, current_win_streak, "
            "longest_win_streak, current_loss_streak) values (1, 7, 4, 3, 0, 2, 1)")
con.commit(); con.close()
'''


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


def run(code):
    """Runs `code` in a fresh interpreter with DB = a new temp SQLite path; returns (rc, stdout, stderr)."""
    db_path = os.path.join(tempfile.mkdtemp(), 'mig.db').replace('\\', '/')
    env = {k: v for k, v in os.environ.items() if k not in ('ENV', 'SECRET_KEY', 'ALLOWED_ORIGINS')}
    env.update(DATABASE_URL='sqlite:///' + db_path, TURN_TIMER_THREAD='0')
    proc = subprocess.run([sys.executable, '-c', f'DB = {db_path!r}\n' + PRELUDE + code], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout.strip(), proc.stderr


def test_fresh_database_matches_the_models():
    rc, out, err = run('''
import app as appmod
from alembic.script import ScriptDirectory
with appmod.app.app_context():
    head = ScriptDirectory.from_config(appmod.migrate.get_config(appmod.MIGRATIONS_DIR)).get_current_head()
print("version", version(DB) == [head], "diff", schema_diff(appmod) == [])
import sqlalchemy as sa
appmod.db.metadata.tables["users"].append_column(sa.Column("nickname", sa.String(20)))   # a model change...
print("drift_detected", any("nickname" in str(d) for d in schema_diff(appmod)))          # ...without a migration
''')
    check("a fresh database is created by the migrations and is at the latest revision",
          rc == 0 and 'version True' in out, (rc, out, err[-400:]))
    check("migrations and models describe exactly the same schema (fails if a model changes without a migration)",
          rc == 0 and 'diff True' in out, (out, err[-400:]))
    check("...and that guard really notices a model change that has no migration", 'drift_detected True' in out, out)


def test_pre_migration_database_is_adopted_with_its_data():
    rc, out, err = run(LEGACY_DB + '''
import app as appmod
from alembic.script import ScriptDirectory
with appmod.app.app_context():
    head = ScriptDirectory.from_config(appmod.migrate.get_config(appmod.MIGRATIONS_DIR)).get_current_head()
con = sqlite3.connect(DB)
user = con.execute("select username, email, password_hash from users where id = 1").fetchone()
stats = con.execute("select total_matches, total_wins, total_losses from user_stats where user_id = 1").fetchone()
con.close()
print("adopted", version(DB) == [head])
print("user", user == ("old_player", "old@x.io", "hash-kept"), "stats", stats == (7, 4, 3))
con = sqlite3.connect(DB)
print("session_version", con.execute("select session_version from users where id = 1").fetchone() == (0,))
print("keys", con.execute("select username, username_key from users order by id").fetchall()
      == [("old_player", "old_player"), ("Old_Vegeta", "old_vegeta")])
con.close()
print("diff", schema_diff(appmod) == [])
''')
    check("a database made before migrations existed is adopted and brought to the latest revision",
          rc == 0 and 'adopted True' in out, (rc, out, err[-400:]))
    check("...keeping its accounts and stats untouched", 'user True stats True' in out, out)
    check("...and later migrations apply to it (existing accounts get session_version 0)",
          'session_version True' in out, out)
    check("...and every existing account gets its lower-cased username key", 'keys True' in out, out)
    check("...and ends up with exactly the models' schema", 'diff True' in out, out)


def test_partial_legacy_database_is_refused():
    rc, out, err = run('''
con = sqlite3.connect(DB)
con.execute("create table users (id integer primary key)")
con.commit(); con.close()
import app
''')
    check("a database with some tables but no migration history and missing tables is refused, not guessed at",
          rc != 0 and 'refusing to guess its schema' in err, (rc, err[-300:]))


def test_database_with_unexpected_columns_is_refused():
    rc, out, err = run(LEGACY_DB + '''
con = sqlite3.connect(DB)
con.execute("alter table users add column nickname varchar(20)")
con.commit(); con.close()
import app
''')
    check("a database whose columns don't exactly match the baseline is refused (no crash half-way through)",
          rc != 0 and 'users columns differ' in err and "extra ['nickname']" in err, (rc, err[-300:]))


def test_look_alike_usernames_stop_the_upgrade():
    rc, out, err = run(LEGACY_DB + '''
con = sqlite3.connect(DB)
con.execute("insert into users (id, username, email, password_hash, created_at) "
            "values (3, 'OLD_PLAYER', 'imp@x.io', 'hash-3', '2026-08-18 20:00:00')")
con.commit(); con.close()
try:
    import app
except BaseException as e:
    print("refused", type(e).__name__)
con = sqlite3.connect(DB)
print("rows", con.execute("select count(*) from users").fetchone()[0])
print("no_key_column", "username_key" not in [r[1] for r in con.execute("pragma table_info(users)")])
con.close()
''')
    check("names that differ only in capitalization stop the upgrade with a clear list (no guessing who to rename)",
          'refused' in out and "differ only in capitalization: 'OLD_PLAYER', 'old_player'" in err, (out, err[-400:]))
    check("...without changing the accounts or adding the column", 'rows 3' in out and 'no_key_column True' in out,
          out)


def test_downgrade_and_upgrade_round_trip():
    rc, out, err = run('''
import app as appmod
from flask_migrate import downgrade, upgrade
with appmod.app.app_context():
    downgrade(directory=appmod.MIGRATIONS_DIR, revision="base")
    con = sqlite3.connect(DB)
    left = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name != 'alembic_version'")]
    con.close()
    upgrade(directory=appmod.MIGRATIONS_DIR)
    upgrade(directory=appmod.MIGRATIONS_DIR)   # second run is a no-op
print("empty_after_downgrade", left == [], "diff", schema_diff(appmod) == [])
''')
    check("every migration can be undone (downgrade to base removes all tables)",
          rc == 0 and 'empty_after_downgrade True' in out, (rc, out, err[-400:]))
    check("...and re-applied, twice, ending at the models' schema", 'diff True' in out, out)


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_')]

if __name__ == '__main__':
    for t in TESTS:
        print(f"{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print(f"All {len(TESTS)} test functions passed.")
