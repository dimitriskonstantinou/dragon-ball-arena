"""
PostgreSQL checks (production database; DEPLOY_PLAN Stage 2). Run with:

    TEST_POSTGRES_URL=postgresql+psycopg://dba:dbatest@127.0.0.1:55432/dba_test python test_postgres.py
    (or simply: python tests.py --postgres  -- it starts a throwaway Docker container for you)

Every scenario runs in its own interpreter on its OWN brand-new database (created
and dropped here), so nothing depends on what an earlier run left behind. Without
TEST_POSTGRES_URL it prints SKIPPED and exits 0 (the SQLite suites still run).
"""
import os
import subprocess
import sys
import uuid

FAILURES = []
BACKEND = os.path.dirname(os.path.abspath(__file__))
ADMIN_URL = os.environ.get('TEST_POSTGRES_URL', '')
STEP25_PARENT = '4d7e92ca43bc'   # revision before case-insensitive usernames
STEP27 = '399b42c2815d'          # the draw columns (dropped again by aac3382b42ab)


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


def admin():
    import psycopg
    from sqlalchemy.engine import make_url
    url = make_url(ADMIN_URL).set(drivername='postgresql')
    return psycopg.connect(url.render_as_string(hide_password=False), autocommit=True)


def fresh_database():
    """Creates an empty database and returns (SQLAlchemy URL, name)."""
    from sqlalchemy.engine import make_url
    name = f"dba_t_{uuid.uuid4().hex[:10]}"
    with admin() as con:
        con.execute(f'CREATE DATABASE "{name}"')
    return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False), name


def drop_database(name):
    with admin() as con:
        con.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


PRELUDE = '''
import os, sys
sys.path.insert(0, ".")
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
URL = os.environ["DATABASE_URL"]
ENGINE = sa.create_engine(URL)
def sql(statement, **params):
    with ENGINE.begin() as con:
        result = con.execute(sa.text(statement), params)
        return result.fetchall() if result.returns_rows else None
def columns(table):
    return {c["name"] for c in sa.inspect(ENGINE).get_columns(table)}
def schema_diff(appmod):
    with appmod.app.app_context():
        with appmod.db.engine.connect() as conn:
            return compare_metadata(MigrationContext.configure(conn), appmod.db.metadata)
def migrate_to(revision):
    # Like an older deployment: the schema as it was at `revision`, without importing app.py.
    from flask import Flask
    from flask_migrate import Migrate, upgrade
    from models import db
    old = Flask("old")
    old.config["SQLALCHEMY_DATABASE_URI"] = URL
    db.init_app(old)
    Migrate(old, db, directory=os.path.join(".", "migrations"), render_as_batch=True)
    with old.app_context():
        upgrade(directory=os.path.join(".", "migrations"), revision=revision)
'''


def run(code, extra_env=None):
    """Runs `code` against a brand-new database; returns (rc, stdout, stderr)."""
    url, name = fresh_database()
    try:
        env = {k: v for k, v in os.environ.items() if k not in ('ENV', 'SECRET_KEY', 'ALLOWED_ORIGINS')}
        env.update(DATABASE_URL=url, TURN_TIMER_THREAD='0', LOG_LEVEL='WARNING', **(extra_env or {}))
        proc = subprocess.run([sys.executable, '-c', PRELUDE + code], cwd=BACKEND, env=env,
                              capture_output=True, text=True, timeout=300)
        return proc.returncode, proc.stdout.strip(), proc.stderr
    finally:
        drop_database(name)


def test_fresh_database_matches_the_models():
    rc, out, err = run('''
import app as appmod
from alembic.script import ScriptDirectory
with appmod.app.app_context():
    head = ScriptDirectory.from_config(appmod.migrate.get_config(appmod.MIGRATIONS_DIR)).get_current_head()
print("version", [r[0] for r in sql("select version_num from alembic_version")] == [head])
print("diff", schema_diff(appmod))
print("dialect", ENGINE.dialect.name)
''')
    check("(the scenario really runs on PostgreSQL)", 'dialect postgresql' in out, (out, err[-300:]))
    check("a fresh PostgreSQL database is built by the migrations up to the latest revision",
          rc == 0 and 'version True' in out, (rc, out, err[-400:]))
    check("...and its schema is exactly the models' (types, defaults, indexes)", 'diff []' in out, out)


def test_downgrade_and_upgrade_round_trip():
    rc, out, err = run('''
import app as appmod
from flask_migrate import downgrade, upgrade
with appmod.app.app_context():
    downgrade(directory=appmod.MIGRATIONS_DIR, revision="base")
    left = sorted(sa.inspect(ENGINE).get_table_names())
    upgrade(directory=appmod.MIGRATIONS_DIR)
    upgrade(directory=appmod.MIGRATIONS_DIR)
print("left", [t for t in left if t != "alembic_version"])
print("diff", schema_diff(appmod))
''')
    check("every migration can be undone on PostgreSQL (downgrade to base removes all tables)",
          rc == 0 and 'left []' in out, (rc, out, err[-400:]))
    check("...and re-applied, twice, ending at the models' schema", 'diff []' in out, out)


def test_existing_data_survives_every_later_migration():
    rc, out, err = run(f'''
migrate_to("{STEP25_PARENT}")
sql("insert into users (id, username, email, password_hash, created_at, session_version) values "
    "(1, 'Old_Vegeta', 'veg@x.io', 'h1', now(), 3), (2, 'nappa', 'nap@x.io', 'h2', now(), 0)")
sql("insert into user_stats (user_id, total_matches, total_wins, total_losses, current_win_streak, "
    "longest_win_streak, current_loss_streak) values (1, 7, 4, 3, 0, 2, 1)")
sql("insert into matches (id, player1_id, player2_id, winner_id, started_at, ended_at) values (1, 1, 2, 1, now(), now())")
import app as appmod
print("keys", sql("select username, username_key, session_version from users order by id")
      == [("Old_Vegeta", "old_vegeta", 3), ("nappa", "nappa", 0)])
print("stats", sql("select total_matches, total_wins, total_losses from user_stats") == [(7, 4, 3)])
print("match", sql("select winner_id from matches") == [(1,)])
print("no_draws", not ({{"is_draw"}} & columns("matches")) and not ({{"total_draws"}} & columns("user_stats")))
print("diff", schema_diff(appmod))
''')
    check("a PostgreSQL database with accounts from before Step 25 upgrades to the latest revision",
          rc == 0 and 'diff []' in out, (rc, out, err[-400:]))
    check("...existing accounts get their lower-cased username key, sessions kept", 'keys True' in out, out)
    check("...stats and match results untouched, no draw columns left",
          'stats True' in out and 'match True' in out and 'no_draws True' in out, out)


def test_look_alike_usernames_stop_the_upgrade_without_half_applying():
    rc, out, err = run(f'''
migrate_to("{STEP25_PARENT}")
sql("insert into users (id, username, email, password_hash, created_at, session_version) values "
    "(1, 'Goku', 'g1@x.io', 'h', now(), 0), (2, 'goku', 'g2@x.io', 'h', now(), 0)")
try:
    import app
except BaseException as e:
    print("refused", type(e).__name__)
print("version", [r[0] for r in sql("select version_num from alembic_version")])
print("rows", sql("select count(*) from users")[0][0])
print("no_key_column", "username_key" not in columns("users"))
''')
    check("names differing only in capitalization stop the upgrade with the list",
          'refused' in out and "'Goku', 'goku'" in err, (out, err[-400:]))
    check("...and PostgreSQL rolls the whole upgrade back: nothing half-applied, accounts untouched",
          f"version ['{STEP25_PARENT}']" in out and 'rows 2' in out and 'no_key_column True' in out, out)


def test_database_at_the_draws_revision_upgrades_cleanly():
    rc, out, err = run(f'''
migrate_to("{STEP27}")
sql("insert into users (id, username, username_key, email, password_hash, created_at, session_version) values "
    "(1, 'Gohan', 'gohan', 'g@x.io', 'h', now(), 0), (2, 'Krillin', 'krillin', 'k@x.io', 'h', now(), 0)")
sql("insert into matches (id, player1_id, player2_id, winner_id, started_at, ended_at) values (1, 1, 2, 2, now(), now())")
print("bool_default", sql("select is_draw from matches") == [(False,)])
import app as appmod
print("match", sql("select winner_id from matches") == [(2,)])
print("diff", schema_diff(appmod))
''')
    check("Step 27's boolean column default works on PostgreSQL (sa.false(), not the integer 0)",
          'bool_default True' in out, (rc, out, err[-400:]))
    check("a PostgreSQL database at Step 27's revision upgrades cleanly, keeping its matches",
          rc == 0 and 'match True' in out and 'diff []' in out, (rc, out, err[-400:]))


def test_postgres_enforces_what_sqlite_does_not():
    rc, out, err = run('''
import app as appmod
from sqlalchemy.exc import DataError
web = appmod.app.test_client()
ok = web.post("/api/register", json={"username": "A" * 20, "email": "twenty@x.io", "password": "secret1"}).status_code
try:
    sql("insert into users (username, username_key, email, password_hash, created_at, session_version) "
        "values (:n, :n, 'long@x.io', 'h', now(), 0)", n="B" * 21)
    too_long = "accepted"
except DataError:
    too_long = "rejected"
print("twenty", ok, "twentyone", too_long)
print("health", web.get("/healthz").status_code)
''', {'REGISTER_LIMIT': '1000'})
    check("a 20-character username (the maximum) registers on PostgreSQL", 'twenty 201' in out, (rc, out, err[-400:]))
    check("...and the database itself refuses 21 characters (SQLite would silently store them)",
          'twentyone rejected' in out, out)
    check("/healthz answers 200 on PostgreSQL", 'health 200' in out, out)


def test_release_step_seed_db():
    rc, out, err = run('''
import subprocess, sys
def seed():
    p = subprocess.run([sys.executable, "seed_db.py"], capture_output=True, text=True, env=os.environ)
    return p.returncode, p.stdout + p.stderr
first, second = seed(), seed()
print("first", first[0], "second", second[0])
print("chars", sql("select count(*) from characters")[0][0])
print("second_out", second[1].strip().splitlines()[-1] if second[1].strip() else "")
''')
    check("the release step (python seed_db.py) migrates + registers the roster on PostgreSQL",
          rc == 0 and 'first 0' in out and 'chars 0' not in out, (rc, out, err[-400:]))
    check("...and running it again is a no-op (0 added, 0 updated)",
          'second 0' in out and '0 added, 0 updated' in out, out)


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_')]

if __name__ == '__main__':
    if not ADMIN_URL:
        print("SKIPPED: set TEST_POSTGRES_URL (or run: python tests.py --postgres)")
        raise SystemExit(0)
    for t in TESTS:
        print(f"{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print(f"All {len(TESTS)} test functions passed.")
