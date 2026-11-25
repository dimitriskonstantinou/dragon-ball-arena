from flask import Flask, g, request, send_from_directory, session, jsonify
from flask_migrate import Migrate, stamp, upgrade
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlalchemy as sa
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
import copy
import logging
import os
import re
import sys
import threading
import time
import uuid
from contextlib import contextmanager

import atexit
import platform

import config
import content_loader
import game_engine
import logging_setup
import rate_limit
from game_engine import GameError
from models import db, User, UserStats, Character, UserCharacter, Match
from sqlalchemy.exc import IntegrityError

log = logging.getLogger('app')                   # startup, database, unexpected errors (not __name__: that is
                                                  # '__main__' under `python app.py`)
http_log = logging.getLogger('arena.http')        # one line per HTTP request
auth_log = logging.getLogger('arena.auth')        # accounts + security events
sock_log = logging.getLogger('arena.socket')      # game connections
match_log = logging.getLogger('arena.match')      # matchmaking, turns, results
stats_log = logging.getLogger('arena.stats')      # periodic health numbers
STARTED = time.monotonic()
STATS_EVERY_SECONDS = 60

# Exit code 3 = gunicorn's "worker failed to boot": gunicorn then STOPS with this message
# instead of restarting the worker forever (a misconfigured deploy must fail loudly).
CONFIG_ERROR_EXIT_CODE = 3

try:
    settings = config.load()
except config.ConfigError as e:
    print(f"Configuration error: {e}", file=sys.stderr, flush=True)
    raise SystemExit(CONFIG_ERROR_EXIT_CODE)


# One format for every way the app runs, set up before anything logs (incl. the
# migrations run at import below). See logging_setup.py for what goes where.
logging_setup.configure(settings.log_level, settings.log_format)

app = Flask(__name__)
if settings.trusted_proxies:
    # Real client IP / scheme from the proxy's X-Forwarded-* headers (rate limits, Secure cookies).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=settings.trusted_proxies, x_proto=settings.trusted_proxies)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.normpath(os.path.join(BASE_DIR, '..', 'frontend'))

app.config['SECRET_KEY'] = settings.secret_key
app.config['SQLALCHEMY_DATABASE_URI'] = settings.database_url
# Login cookie: no JS access, not sent with other sites' requests, HTTPS-only once deployed.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = settings.is_production_like
# Logins expire after SESSION_DAYS without a visit: Flask checks the cookie's signed
# timestamp server-side, and each request renews it (active players stay logged in).
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=settings.session_days)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
MIGRATIONS_DIR = os.path.join(BASE_DIR, 'migrations')
migrate = Migrate(app, db, directory=MIGRATIONS_DIR, render_as_batch=True)  # batch: SQLite can't ALTER much
# None = same origin only (development); deployments must list their https origins (config.py).
socketio = SocketIO(app, async_mode=settings.socketio_async_mode,
                    cors_allowed_origins=list(settings.allowed_origins) or None)
logging_setup.unify_library_loggers()   # engineio/socketio just added their own output handlers

GAMES = {}
MATCHMAKING_QUEUE = []
SID_ROOM_MAP = {}  # sid -> roomId, for O(1) disconnect/forfeit lookup
USER_SIDS = {}     # user_id -> {socket id: page id or None} of that account's open connections, newest last
USER_ROOMS = {}    # user_id -> roomId of the account's live match
USER_SIDS_LOCK = threading.Lock()

# The server runs every Socket.IO event in its own thread, so shared state needs
# locks. Lock order is always MATCHMAKING_LOCK -> a room lock, never the reverse.
ROOM_LOCKS = {}                        # room_id -> RLock, one per live match (see locked_match)
MATCHMAKING_LOCK = threading.Lock()    # MATCHMAKING_QUEUE + seat checks + creating matches

SERVER_ERROR_MSG = "Something went wrong on the server. Please try again."
MOVED_MSG = "Your match continues in another page or tab. This one is closed."
PAGE_ID_RE = re.compile(r'[A-Za-z0-9_-]{8,64}')
MATCH_FAILED_MSG = "The match could not be started. Reload the page and search again."

# Turn timer (BE-1): every turn has a deadline; one background ticker passes
# expired turns (game_engine.timeout_turn has the rules, incl. forfeit).
TURN_SECONDS = settings.turn_seconds
TIMER_TICK_SECONDS = 1.0
TURN_TIMER_THREAD = settings.turn_timer_thread  # tests drive the timer by hand instead

# Reconnect grace window (BE-2): a player who drops mid-match has this long to
# come back (same account, any tab) before forfeiting. user_id -> room_id.
RECONNECT_SECONDS = settings.reconnect_seconds
DISCONNECTED_USERS = {}
_timer_started = False
_header_warned = False


def now():
    """The server clock for turn deadlines (tests move it by patching time.time)."""
    return time.time()


def client_ip():
    """The visitor's address: from the header this host is configured to put it in (CLIENT_IP_HEADER), else
    the connection's own address (after TRUSTED_PROXIES). For HTTP requests and Socket.IO events alike."""
    ip = header_ip()
    return str(ip) if ip else request.remote_addr


def header_ip():
    name = settings.client_ip_header
    return rate_limit.parse_ip(request.environ.get('HTTP_' + name.upper().replace('-', '_'))) if name else None


def visitor_key():
    """What the rate limits count. Without a usable header everyone behind the host would share one limit."""
    global _header_warned
    if settings.client_ip_header and not _header_warned and header_ip() is None:
        _header_warned = True
        http_log.warning("Visitor address header missing or malformed: header=%s path=%s (logged once)",
                         settings.client_ip_header, request.path)
    return rate_limit.visitor_key(client_ip())


def who():
    """'user=.. room=.. role=.. sid=..' for the connection handling this event (log context)."""
    sid = request.sid
    room_id = SID_ROOM_MAP.get(sid)
    game = GAMES.get(room_id)
    role = next((r for r in ('p1', 'p2') if game and game['players'][r]['id'] == sid), None)
    if role:
        user_id = game['players'][role]['user_id']
    else:
        with USER_SIDS_LOCK:
            user_id = next((u for u, sids in USER_SIDS.items() if sid in sids), None)
    return f"user={user_id} room={room_id} role={role} sid={sid[:6]}"


def report_error(e, event, data=None):
    """GameErrors are rule violations -- tell the player (logged at DEBUG). Anything
    else is a bug: log the full traceback WITH its context and don't leak internals."""
    if isinstance(e, GameError):
        sock_log.debug("Refused %s: %s -- %s", event, who(), e)
        emit('error-msg', str(e), to=request.sid)
    else:
        log.exception("Unhandled error in %s: %s payload=%s", event, who(), logging_setup.short(data))
        emit('error-msg', SERVER_ERROR_MSG, to=request.sid)


# The roster, validated once at import: invalid content stops the server here.
# Gameplay reads characters only from this in-memory catalog, never the DB.
CATALOG = content_loader.catalog()


def sync_character_registry(catalog=None):
    """Keeps the `characters` table -- now only an id registry for foreign keys
    (unlocks, missions) -- in step with the content files. Inserts/updates,
    never deletes: a character removed from content stays registered (accounts
    may reference it) and simply stops being offered to players. The legacy
    skills_json column is emptied so no stale copy can be read; it goes away
    with the first migration (DB-1). Returns (added, updated) counts."""
    catalog = CATALOG if catalog is None else catalog
    rows = {row.id: row for row in Character.query.all()}
    added = updated = 0
    for cid, char in catalog.items():
        row = rows.get(cid)
        if row is None:
            db.session.add(Character(id=cid, name=char['name'], image=char['image'], health=char['health'],
                                     skills_json='[]', is_starter=True))
            added += 1
        elif (row.name, row.image, row.health, row.skills_json) != (char['name'], char['image'], char['health'], '[]'):
            row.name, row.image, row.health, row.skills_json = char['name'], char['image'], char['health'], '[]'
            updated += 1
    db.session.commit()
    return added, updated


# The first migration: exactly the tables db.create_all() made before Step 23.
BASELINE_REVISION = 'def555b6f5cf'
# Exact columns of that baseline (it never changes). Adoption requires a perfect match.
BASELINE_COLUMNS = {
    'characters': {'id', 'name', 'image', 'health', 'skills_json', 'is_starter'},
    'users': {'id', 'username', 'email', 'password_hash', 'created_at'},
    'matches': {'id', 'player1_id', 'player2_id', 'winner_id', 'started_at', 'ended_at'},
    'missions': {'id', 'name', 'description', 'requirement', 'reward_character_id'},
    'user_characters': {'id', 'user_id', 'character_id', 'unlocked_at'},
    'user_stats': {'user_id', 'total_matches', 'total_wins', 'total_losses', 'current_win_streak',
                   'longest_win_streak', 'current_loss_streak', 'last_match_at'},
    'user_mission_progress': {'id', 'user_id', 'mission_id', 'progress', 'completed_at'},
}


def upgrade_database():
    """Brings the schema to the latest migration (backend/migrations). A
    database made before migrations existed (tables, but no alembic_version)
    is adopted first: if it has every baseline table it's stamped at the
    baseline -- its tables are exactly what that migration creates -- and then
    upgraded like any other. Nothing in it is changed or deleted by adoption."""
    inspector = sa.inspect(db.engine)
    tables = set(inspector.get_table_names())
    if tables and 'alembic_version' not in tables:
        problems = [f"missing table {t}" for t in sorted(set(BASELINE_COLUMNS) - tables)]
        for table in sorted(set(BASELINE_COLUMNS) & tables):
            columns = {c['name'] for c in inspector.get_columns(table)}
            if columns != BASELINE_COLUMNS[table]:
                problems.append(f"{table} columns differ (extra {sorted(columns - BASELINE_COLUMNS[table])}, "
                                f"missing {sorted(BASELINE_COLUMNS[table] - columns)})")
        if problems:
            raise RuntimeError("Database has tables but no migration history, and doesn't match the baseline "
                               f"schema ({'; '.join(problems)}); refusing to guess its schema. Inspect it by hand.")
        log.info("Adopting a pre-migration database at the baseline revision %s", BASELINE_REVISION)
        stamp(directory=MIGRATIONS_DIR, revision=BASELINE_REVISION)
    upgrade(directory=MIGRATIONS_DIR)


def ensure_db_ready():
    """Migrates the schema to the latest version and syncs the character
    registry. No manual reseed is ever needed after editing content files."""
    with app.app_context():
        upgrade_database()
        added, updated = sync_character_registry()
        if added or updated:
            log.info("Character registry synced: %d added, %d updated", added, updated)


ensure_db_ready()


def log_shutdown():
    try:
        log.info("Server stopping: version=%s uptime=%ds live_matches=%d (in-memory matches end with the process)",
                 settings.app_version, time.monotonic() - STARTED, len(GAMES))
    except Exception:
        pass   # interpreter shutdown: logging may already be gone


log.info("Server starting: version=%s env=%s python=%s async_mode=%s database=%s roster=%d characters "
         "turn=%ss reconnect=%ss proxies=%d ip_header=%s log=%s/%s", settings.app_version, settings.env,
         platform.python_version(), settings.socketio_async_mode, logging_setup.safe_database_url(settings.database_url),
         len(CATALOG), settings.turn_seconds, settings.reconnect_seconds, settings.trusted_proxies,
         settings.client_ip_header or 'none',
         settings.log_level, settings.log_format)
atexit.register(log_shutdown)


def current_user():
    """The logged-in account, or None. A cookie issued before the account's
    last logout (older session_version) no longer counts (SEC-4)."""
    uid = session.get('user_id')
    if not uid:
        return None
    user = db.session.get(User, uid)
    if user is None or session.get('sv') != user.session_version:
        if not g.get('stale_cookie_logged'):
            g.stale_cookie_logged = True
            auth_log.info("Rejected a login cookie from before a logout-everywhere: user=%s ip=%s", uid,
                          client_ip())
        return None
    return user


def start_session(user):
    """Fresh session for `user` (cleared first: no session fixation), tied to
    the account's current session_version and expiring after SESSION_DAYS."""
    session.clear()
    session.permanent = True
    session['user_id'] = user.id
    session['sv'] = user.session_version


def unlocked_character_ids(user):
    """TEMP unlock policy until missions exist (see the Mission models):
    every account has every active character -- including ones added after
    it registered -- with no DB query. Replace this when unlocks are built."""
    return list(CATALOG)


PHOTOS_URL = '/photos/'   # site-relative: the same domain as the page, whatever it is


def characters_for_user(user):
    """Fresh copies of this account's characters, ready for a match, with
    image paths turned into site-relative URLs (/photos/...): they work under
    any domain and behind a proxy, and never echo the request's Host header.
    Never modifies the shared catalog."""
    result = {}

    def skill_urls(effects):
        # Images swapped in later by prime_skill (e.g. Puar -> Spirit Ball) need
        # the same URL as regular skill images, or the browser 404s on them.
        for effect in effects:
            if effect.get('primed_image'):
                effect['primed_image'] = PHOTOS_URL + 'skills/' + effect['primed_image']
            skill_urls(effect.get('primed_effects', []))

    for cid in unlocked_character_ids(user):
        char_dict = copy.deepcopy(CATALOG[cid])
        char_dict['defense'] = 0
        char_dict['image'] = PHOTOS_URL + char_dict['image']
        for skill in char_dict['skills']:
            if skill.get('image'):
                skill['image'] = PHOTOS_URL + 'skills/' + skill['image']
            skill_urls(skill['effects'])
        result[cid] = char_dict
    return result


def persist_match_result(game, winner_role):
    p1 = game['players']['p1']
    p2 = game['players']['p2']
    p1_uid = p1.get('user_id')
    p2_uid = p2.get('user_id')
    if not p1_uid or not p2_uid:
        return  # shouldn't happen once matchmaking requires login; stay defensive

    if winner_role not in ('p1', 'p2'):   # there are no draws (user, 2026-11-21)
        raise ValueError(f"unknown match result {winner_role!r}")
    winner_uid = game['players'][winner_role]['user_id']
    started_at_raw = game.get('started_at')
    started_at = datetime.fromisoformat(started_at_raw) if started_at_raw else datetime.now(timezone.utc)

    db.session.add(Match(player1_id=p1_uid, player2_id=p2_uid, winner_id=winner_uid,
                          started_at=started_at, ended_at=datetime.now(timezone.utc)))

    for uid in (p1_uid, p2_uid):
        stats = db.session.get(UserStats, uid)
        if stats:
            stats.record_result(won=uid == winner_uid)

    db.session.commit()


def broadcast_state(game):
    """Sends each player their own filtered view (game_engine.view_for) --
    never the raw state, which holds hidden info: the opponent's queued
    moves, invisible traps, socket/account ids."""
    seconds_left = None
    if game.get('turn_deadline') is not None and not game.get('winner'):
        seconds_left = max(0, round(game['turn_deadline'] - now()))
    for role in ('p1', 'p2'):
        view = game_engine.view_for(game, role)
        view.pop('turn_deadline', None)  # server clock; clients get a relative countdown instead
        view['turn_seconds_left'] = seconds_left
        for r in ('p1', 'p2'):
            view['players'][r]['connected'] = game['players'][r].get('disconnected_at') is None
        socketio.emit('update-state', view, to=game['players'][role]['id'])


def start_turn_clock(game):
    game['turn_deadline'] = now() + TURN_SECONDS


def check_turn_timers():
    """Passes every turn whose deadline has expired. Runs in the ticker
    thread (needs an app context for end_game's DB write); each match is
    handled under its lock, and the deadline is re-checked there, so a commit
    that lands at the same moment wins and the timeout backs off."""
    for room_id, game in list(GAMES.items()):
        if game.get('turn_deadline') is None or now() < game['turn_deadline']:
            continue
        lock = ROOM_LOCKS.get(room_id)
        if lock is None:
            continue
        with lock:
            if GAMES.get(room_id) is not game or game.get('winner') or now() < game['turn_deadline']:
                continue
            timed_out = game['turn']
            try:
                strikes = game_engine.timeout_turn(game)
            except Exception:
                log.exception("Turn timeout failed: room=%s turn=%s", room_id, timed_out)
                continue
            match_log.info("Turn timed out: room=%s role=%s user=%s strikes=%d/%d", room_id, timed_out,
                           game['players'][timed_out]['user_id'], strikes, game_engine.TIMEOUTS_TO_FORFEIT)
            if game.get('winner'):
                reason, cause = None, 'ko'
                if strikes >= game_engine.TIMEOUTS_TO_FORFEIT:
                    reason, cause = (f"{timed_out.upper()} RAN OUT OF TIME {strikes} TURNS IN A ROW AND FORFEITS. "
                                     f"{game['winner'].upper()} WINS!"), 'timeouts'
                end_game(room_id, game['winner'], reason=reason, cause=cause)
            else:
                start_turn_clock(game)
                socketio.emit('message', f"{timed_out.upper()} ran out of time -- turn passed "
                                         f"({strikes}/{game_engine.TIMEOUTS_TO_FORFEIT} in a row forfeits).", to=room_id)
                broadcast_state(game)


def check_disconnect_timers():
    """Forfeits players who dropped out of a match and didn't come back
    within RECONNECT_SECONDS (runs in the ticker, under each match's lock)."""
    for user_id, room_id in list(DISCONNECTED_USERS.items()):
        game = GAMES.get(room_id)
        lock = ROOM_LOCKS.get(room_id)
        if game is None or lock is None:
            DISCONNECTED_USERS.pop(user_id, None)
            continue
        with lock:
            if GAMES.get(room_id) is not game or game.get('winner'):
                continue
            gone = [r for r in ('p1', 'p2') if game['players'][r].get('disconnected_at') is not None
                    and now() >= game['players'][r]['disconnected_at'] + RECONNECT_SECONDS]
            if not gone:
                continue
            loser = min(gone, key=lambda r: game['players'][r]['disconnected_at'])  # first to leave
            winner = 'p2' if loser == 'p1' else 'p1'
            end_game(room_id, winner, reason=f"{loser.upper()} DIDN'T COME BACK IN TIME. {winner.upper()} WINS!",
                     cause='disconnect')


def log_stats():
    """One line of health numbers (every STATS_EVERY_SECONDS from the ticker)."""
    with USER_SIDS_LOCK:
        players, sockets = len(USER_SIDS), sum(len(s) for s in USER_SIDS.values())
    stats_log.info("Stats: live_matches=%d queued=%d players_online=%d sockets=%d waiting_to_reconnect=%d "
                   "uptime=%ds", len(GAMES), len(MATCHMAKING_QUEUE), players, sockets, len(DISCONNECTED_USERS),
                   time.monotonic() - STARTED)


def turn_timer_loop():
    last_stats = time.monotonic()
    while True:
        socketio.sleep(TIMER_TICK_SECONDS)
        try:
            with app.app_context():
                check_turn_timers()
                check_disconnect_timers()
            if time.monotonic() - last_stats >= STATS_EVERY_SECONDS:
                last_stats = time.monotonic()
                log_stats()
        except Exception:
            log.exception("Turn timer loop error")


def ensure_turn_timer():
    """Starts the single ticker (turn timer, reconnect forfeits, stats) on the first
    connection or match (caller holds MATCHMAKING_LOCK)."""
    global _timer_started
    if TURN_TIMER_THREAD and not _timer_started:
        _timer_started = True
        socketio.start_background_task(turn_timer_loop)

def end_game(room_id, winner, reason=None, cause='ko'):
    """Finishes a match exactly once: records the result, sends both players
    the final state + message, then forgets the room entirely (GAMES entry,
    sid mappings, Socket.IO room) so finished matches don't pile up in memory.
    The room is popped first: a second call (e.g. a disconnect racing the final
    commit) finds nothing and returns. ('winner' can't be the guard -- the
    engine sets it before this runs.) Late events from either player then get
    "You are not in a match." from current_match()."""
    game = GAMES.pop(room_id, None)
    if not game:
        return
    ROOM_LOCKS.pop(room_id, None)  # threads still waiting on it re-check GAMES and back off
    loser = 'p2' if winner == 'p1' else 'p1'
    try:
        duration = (datetime.now(timezone.utc) - datetime.fromisoformat(game['started_at'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        duration = -1
    match_log.info("Match ended: room=%s cause=%s winner=%s(user=%s) loser=%s(user=%s) turns=%s duration=%ds",
                   room_id, cause, winner, game['players'][winner].get('user_id'), loser,
                   game['players'][loser].get('user_id'), game.get('turn_count'), duration)
    game['winner'] = winner
    for p_key in ('p1', 'p2'):
        SID_ROOM_MAP.pop(game['players'][p_key]['id'], None)
        if USER_ROOMS.get(game['players'][p_key].get('user_id')) == room_id:
            USER_ROOMS.pop(game['players'][p_key]['user_id'], None)
        if DISCONNECTED_USERS.get(game['players'][p_key].get('user_id')) == room_id:
            DISCONNECTED_USERS.pop(game['players'][p_key]['user_id'], None)

    # Saved before the broadcast so the client's stats badge refresh sees it --
    # but a database failure must never stop the players from seeing the end.
    try:
        persist_match_result(game, winner)
    except Exception:
        # Socket events get a fresh session anyway, but end_game will also run
        # from background tasks (turn timer), where nothing else would clean up.
        db.session.rollback()
        log.exception("Could not save match result: room=%s winner=%s p1_user=%s p2_user=%s started_at=%s",
                      room_id, winner, game['players']['p1'].get('user_id'),
                      game['players']['p2'].get('user_id'), game.get('started_at'))

    broadcast_state(game)
    message = reason or f"GAME OVER! {winner.upper()} WINS!"
    socketio.emit('message', message, to=room_id)
    socketio.close_room(room_id)


# --- request log ---------------------------------------------------------------

@app.before_request
def start_request_timer():
    g.request_started = time.perf_counter()


@app.after_request
def log_request(response):
    """One line per request: API calls at INFO, static files and /healthz at DEBUG
    (the host polls /healthz). Socket.IO traffic is logged per event, not here."""
    elapsed = (time.perf_counter() - g.get('request_started', time.perf_counter())) * 1000
    level = logging.INFO if request.path.startswith('/api/') else logging.DEBUG
    if response.status_code >= 500:
        level = logging.ERROR
    http_log.log(level, "%s %s %d %.1fms ip=%s user=%s", request.method, request.path, response.status_code,
                 elapsed, client_ip(), session.get('user_id'))
    return response


# --- static file / photo serving --------------------------------------------

@app.route('/healthz')
def healthz():
    """For the host's health checks: 200 when the database answers (the
    content is validated before the server starts at all), else 503. Says
    nothing about the setup -- anyone can call it."""
    try:
        db.session.execute(sa.select(1))
        ok = True
    except Exception:
        log.exception("Health check: database unreachable")
        try:
            db.session.rollback()
        except Exception:
            pass   # the connection is gone; still answer 503, not 500
        ok = False
    response = jsonify({'status': 'ok' if ok else 'unavailable'})
    response.status_code = 200 if ok else 503
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/photos/<path:filename>')
def serve_image(filename):
    return send_from_directory('photos', filename)

@app.route('/')
def serve_frontend_index():
    return send_from_directory(FRONTEND_DIR, 'index.html')

@app.route('/<path:filename>')
def serve_frontend_asset(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# --- auth (plain HTTP, not Socket.IO) ---------------------------------------

# Per client IP (SEC-3). Failed logins and created accounts count; when over the
# limit every attempt from that IP is refused until the window has passed.
login_limiter = rate_limit.SlidingWindowLimiter(settings.login_failure_limit, settings.login_window_seconds,
                                                clock=lambda: now())
register_limiter = rate_limit.SlidingWindowLimiter(settings.register_limit, settings.register_window_seconds,
                                                   clock=lambda: now())


def too_many(what, wait):
    auth_log.warning("Rate limit hit: too many %s ip=%s retry_after=%ss", what, client_ip(), wait)
    response = jsonify({'error': f"Too many {what}. Try again in {wait} seconds.", 'retry_after': wait})
    response.status_code = 429
    response.headers['Retry-After'] = str(wait)
    return response


# New usernames: plain ASCII letters, digits, _ and - (so lower-casing is
# unambiguous and no look-alike Unicode names). Emails: a basic shape check only;
# real verification needs a confirmation mail (later).
USERNAME_RE = re.compile(r'[A-Za-z0-9_-]{3,20}')
EMAIL_RE = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s.]+')


def refuse_registration(reason, message, status):
    auth_log.info("Registration refused: reason=%s ip=%s", reason, client_ip())
    return jsonify({'error': message}), status


@app.route('/api/register', methods=['POST'])
def register():
    wait = register_limiter.retry_after(visitor_key())
    if wait:
        return too_many("new accounts from your network", wait)
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not username or not email or not password:
        return refuse_registration('missing_fields', 'username, email and password are required', 400)
    if not (3 <= len(username) <= 20):
        return refuse_registration('username_length', 'username must be 3-20 characters', 400)
    if not USERNAME_RE.fullmatch(username):
        return refuse_registration('username_characters', 'username may only contain letters, digits, _ and -', 400)
    if len(email) > 255 or not EMAIL_RE.fullmatch(email):
        return refuse_registration('invalid_email', 'please enter a valid email address', 400)
    if len(password) < 6:
        return refuse_registration('short_password', 'password must be at least 6 characters', 400)
    taken = account_conflict(username, email)
    if taken:
        return refuse_registration(taken.replace(' ', '_'), taken, 409)

    user = User(username=username, username_key=User.key_for(username), email=email,
                password_hash=generate_password_hash(password))
    try:
        db.session.add(user)
        db.session.flush()  # assigns user.id, needed by the rows below
        db.session.add(UserStats(user_id=user.id))
        # Unlock rows are recorded for the future mission system; today access is
        # decided by unlocked_character_ids() (every active character).
        for cid in CATALOG:
            db.session.add(UserCharacter(user_id=user.id, character_id=cid))
        db.session.commit()
    except IntegrityError:
        # Someone registered the same name/email between our check and this
        # write (two requests at once): the unique index decided. Say so cleanly.
        db.session.rollback()
        taken = account_conflict(username, email) or 'username already taken'
        return refuse_registration(taken.replace(' ', '_') + '_simultaneous', taken, 409)
    register_limiter.hit(visitor_key())
    auth_log.info("Account created: user=%s name=%s ip=%s", user.id, user.username, client_ip())

    start_session(user)
    return jsonify(user.to_dict()), 201

def account_conflict(username, email):
    """The 'already taken' message for a new account, or None."""
    if User.query.filter_by(username_key=User.key_for(username)).first():
        return 'username already taken'
    if User.query.filter_by(email=email).first():
        return 'email already registered'
    return None


@app.route('/api/login', methods=['POST'])
def login():
    wait = login_limiter.retry_after(visitor_key())
    if wait:
        return too_many("failed login attempts", wait)
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    user = User.query.filter_by(username_key=User.key_for(username)).first()
    if not user or not check_password_hash(user.password_hash, password):
        login_limiter.hit(visitor_key())
        if user:
            auth_log.warning("Login failed: wrong password user=%s ip=%s", user.id, client_ip())
        else:
            auth_log.warning("Login failed: unknown account name=%s ip=%s", logging_setup.short(username, 40),
                             client_ip())
        return jsonify({'error': 'invalid username or password'}), 401

    start_session(user)
    auth_log.info("Login: user=%s ip=%s", user.id, client_ip())
    return jsonify(user.to_dict())

@app.route('/api/logout', methods=['POST'])
def logout():
    """Logs the account out everywhere: bumping session_version invalidates
    every copy of its login cookie on every device (incl. a stolen one), and
    its open game connections are closed (a match in progress then gets the
    usual reconnect grace period)."""
    user = current_user()
    if user:
        user.session_version += 1
        db.session.commit()
        with USER_SIDS_LOCK:
            sids = list(USER_SIDS.get(user.id, ()))
        for sid in sids:
            socketio.server.disconnect(sid)
        auth_log.info("Logout (every device): user=%s closed_connections=%d ip=%s", user.id, len(sids),
                      client_ip())
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
def me():
    user = current_user()
    if not user:
        return jsonify({'error': 'not logged in'}), 401
    return jsonify(user.to_dict())


# --- Socket.IO: lobby / matchmaking -----------------------------------------

@socketio.on('connect')
def handle_connect(auth=None):
    user = current_user()
    if not user:
        sock_log.debug("Connection without a login: sid=%s ip=%s", request.sid[:6], client_ip())
        emit('auth-required')
        return
    with USER_SIDS_LOCK:
        USER_SIDS.setdefault(user.id, {})[request.sid] = page_id(auth)
    sock_log.info("Connected: user=%s sid=%s ip=%s", user.id, request.sid[:6], client_ip())
    with MATCHMAKING_LOCK:
        ensure_turn_timer()   # the ticker also writes the periodic stats line
    # Display fields only: skill mechanics stay server-side (same rule as view_for).
    char_list = [game_engine.strip_skill_internals(c) for c in characters_for_user(user).values()]
    emit('character-list', char_list)
    replaced = rejoin_match(user)
    if replaced:
        # Usually a connection the network hasn't reported as closed yet; a duplicated tab sees why it stops.
        # (Not under the match's lock: the disconnect handler takes MATCHMAKING_LOCK first.)
        emit('error-msg', MOVED_MSG, to=replaced)
        socketio.server.disconnect(replaced)


def rejoin_match(user):
    """If this account is in a match, attach this new connection to it when the player
    dropped out (any page: reload, new tab, other device), or when it is the SAME page as the
    one in the seat -- reloaded, or reconnecting after a network drop. On a real network that
    old connection can still count as open here (Render reports it closed 10 s late, BE-15).
    Another tab never takes over a connected seat. Returns the connection it replaced, if that
    one still counts as open."""
    room_id = USER_ROOMS.get(user.id)
    lock = ROOM_LOCKS.get(room_id)
    if lock is None:
        return None
    with lock:
        game = GAMES.get(room_id)
        if game is None or game.get('winner'):
            return None
        role = next((r for r in ('p1', 'p2') if game['players'][r]['user_id'] == user.id), None)
        if role is None:
            return None
        player = game['players'][role]
        if player['id'] == request.sid:
            return None   # the old connection's goodbye came in meanwhile and already handed us the seat
        was_gone = player.get('disconnected_at') is not None
        page = page_of(user.id, request.sid)
        if not was_gone and (page is None or page != player.get('page')):
            return None
        old_sid = player['id']
        if not give_seat(room_id, game, role, request.sid):
            return None
        if was_gone:
            match_log.info("Player rejoined: room=%s role=%s user=%s", room_id, role, user.id)
            socketio.emit('message', f"{role.upper()} RECONNECTED.", to=room_id)
        else:
            match_log.info("Seat moved: room=%s role=%s user=%s from=%s to=%s why=same_page", room_id, role, user.id,
                           old_sid[:6], request.sid[:6])
        broadcast_state(game)
        return None if was_gone else old_sid


def give_seat(room_id, game, role, sid):
    """Makes `sid` the connection of `role` (caller holds the match's lock). False, with nothing
    changed, if that connection is closing: a seat given to it would stay empty for good."""
    player = game['players'][role]
    # First the map, THEN the check: handle_disconnect finds the match through the map, so if the
    # connection starts closing after the check, it waits for our lock and counts as leaving again.
    SID_ROOM_MAP[sid] = room_id
    if not is_connected(sid):
        SID_ROOM_MAP.pop(sid, None)
        match_log.info("Rejoin dropped (disconnected): room=%s user=%s sid=%s", room_id, player['user_id'], sid[:6])
        return False
    # The previous connection no longer belongs to this match: its (late) disconnect means nothing.
    SID_ROOM_MAP.pop(player['id'], None)
    leave_room(room_id, sid=player['id'], namespace='/')
    player['id'] = sid
    player['page'] = page_of(player['user_id'], sid)
    player['disconnected_at'] = None
    DISCONNECTED_USERS.pop(player['user_id'], None)
    join_room(room_id, sid=sid, namespace='/')
    emit('game-start', {'roomId': room_id, 'role': role}, to=sid)
    return True


def page_id(auth):
    """The id the page sent when connecting (kept in its sessionStorage: survives a reload, differs
    per tab), or None. Untrusted: only ever compared with pages of the same account."""
    page = auth.get('page') if isinstance(auth, dict) else None
    return page if isinstance(page, str) and PAGE_ID_RE.fullmatch(page) else None


def page_of(user_id, sid):
    with USER_SIDS_LOCK:
        return USER_SIDS.get(user_id, {}).get(sid)


@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    left = None
    with USER_SIDS_LOCK:
        for user_id, sids in list(USER_SIDS.items()):
            if sid in sids:
                left = user_id
                sids.pop(sid, None)
                if not sids:
                    del USER_SIDS[user_id]
    if left is not None:
        sock_log.info("Disconnected: user=%s sid=%s", left, sid[:6])

    with MATCHMAKING_LOCK:
        MATCHMAKING_QUEUE[:] = [p for p in MATCHMAKING_QUEUE if p['id'] != sid]  # in place: keep the same list object

    lock = ROOM_LOCKS.get(SID_ROOM_MAP.get(sid))
    if lock is None:
        SID_ROOM_MAP.pop(sid, None)
        return
    with lock:
        room_id = SID_ROOM_MAP.pop(sid, None)
        game = GAMES.get(room_id)
        if not game or game.get('winner'):
            return
        role = next((r for r in ('p1', 'p2') if game['players'][r]['id'] == sid), None)
        if role is None:
            return
        # Another open page of the same account gets the seat (its own page first, then the newest): a player
        # who is connected must never lose for having left.
        user_id, page = game['players'][role]['user_id'], game['players'][role].get('page')
        with USER_SIDS_LOCK:
            others = list(reversed(USER_SIDS.get(user_id, {}).items()))
        for other_sid, _ in sorted(others, key=lambda item: item[1] is None or item[1] != page):
            if give_seat(room_id, game, role, other_sid):
                match_log.info("Seat moved: room=%s role=%s user=%s from=%s to=%s why=connection_closed", room_id, role,
                               user_id, sid[:6], other_sid[:6])
                broadcast_state(game)
                return
        # Not a forfeit yet: the match waits RECONNECT_SECONDS for this account to
        # come back (rejoin_match); check_disconnect_timers forfeits it after that.
        game['players'][role]['disconnected_at'] = now()
        DISCONNECTED_USERS[game['players'][role]['user_id']] = room_id
        match_log.info("Player left mid-match: room=%s role=%s user=%s grace=%ss", room_id, role,
                       game['players'][role]['user_id'], RECONNECT_SECONDS)
        socketio.emit('message', f"{role.upper()} DISCONNECTED -- waiting up to {RECONNECT_SECONDS}s "
                                 f"for them to come back.", to=room_id)
        broadcast_state(game)

def require(data, **fields):
    """Validates a socket payload: a dict whose listed keys have the given
    types (bools never count as ints). Raises GameError otherwise."""
    if not isinstance(data, dict):
        raise GameError("Invalid request.")
    for key, expected in fields.items():
        value = data.get(key)
        if not isinstance(value, expected) or isinstance(value, bool):
            raise GameError(f"Invalid request: '{key}' is missing or malformed.")
    return data


def current_match():
    """(room_id, game, role) for this connection, from the server's own
    records -- never from roomId/myPlayerKey sent by the client."""
    room_id = SID_ROOM_MAP.get(request.sid)
    game = GAMES.get(room_id)
    if not game or game.get('winner'):
        raise GameError("You are not in a match.")
    role = next((r for r in ('p1', 'p2') if game['players'][r]['id'] == request.sid), None)
    if not role:
        raise GameError("You are not in a match.")
    return room_id, game, role


@contextmanager
def locked_match():
    """Yields (room_id, game, role) for this connection while holding that
    match's lock. Every event that reads or changes a live match must go
    through it: events run in parallel threads, and without the lock e.g. a
    double "commit" could resolve the opponent's turn as well. The match is
    looked up again once the lock is held, because it may have ended while
    this event waited."""
    lock = ROOM_LOCKS.get(SID_ROOM_MAP.get(request.sid))
    if lock is None:
        raise GameError("You are not in a match.")
    with lock:
        yield current_match()


def is_connected(sid):
    """False as soon as a connection starts closing -- the library marks it BEFORE calling
    handle_disconnect. So "connected" means its disconnect cleanup is still to come; that
    cleanup takes the same lock (MATCHMAKING_LOCK / the match's) and will see what we do now."""
    return socketio.server.manager.is_connected(sid, '/')


def user_in_active_match(user_id):
    # list(): other threads add/remove matches while we look.
    return any(not g.get('winner') and user_id in (g['players']['p1']['user_id'], g['players']['p2']['user_id'])
               for g in list(GAMES.values()))


@socketio.on('find-match')
def handle_find_match(selected_char_ids):
    try:
        sid = request.sid
        user = current_user()
        if not user:
            raise GameError("You must be logged in to find a match!")
        if (not isinstance(selected_char_ids, list) or len(selected_char_ids) != 3
                or not all(isinstance(c, str) for c in selected_char_ids)):
            raise GameError("You must select exactly 3 characters!")
        # Duplicate ids would break every charId lookup in the match.
        if len(set(selected_char_ids)) != 3:
            raise GameError("Pick 3 different characters!")

        available_chars = characters_for_user(user)
        my_team = [copy.deepcopy(available_chars[c]) for c in selected_char_ids if c in available_chars]
        if len(my_team) != 3:
            raise GameError("One or more selected characters aren't unlocked on this account!")

        # Seat checks + joining the queue + pairing are one atomic step, or two
        # tabs of the same account could both pass the checks at once.
        with MATCHMAKING_LOCK:
            # This event runs in its own thread, so the player may be gone by now and their
            # disconnect already cleaned up: nothing would ever remove this search again.
            if not is_connected(sid):
                match_log.info("Search dropped (disconnected): user=%s sid=%s", user.id, sid[:6])
                return
            if sid in SID_ROOM_MAP:
                raise GameError("You are already in a match!")
            if any(p['id'] == sid for p in MATCHMAKING_QUEUE):
                raise GameError("You are already searching for a match!")
            # Checked per ACCOUNT, not per connection: otherwise one account in two
            # tabs could be matched against itself (and record its own win + loss).
            if any(p['user_id'] == user.id for p in MATCHMAKING_QUEUE):
                raise GameError("This account is already searching for a match in another tab!")
            if user_in_active_match(user.id):
                raise GameError("This account is already in a match in another tab!")

            MATCHMAKING_QUEUE.append({'id': sid, 'user_id': user.id, 'username': user.username, 'team': my_team})
            match_log.info("Searching: user=%s team=%s queue=%d", user.id, ','.join(selected_char_ids),
                           len(MATCHMAKING_QUEUE))
            emit('match-status', "Searching for opponent...")
            # Skip players whose connection is closing right now (their cleanup waits for this lock).
            MATCHMAKING_QUEUE[:] = [p for p in MATCHMAKING_QUEUE if is_connected(p['id'])]
            if len(MATCHMAKING_QUEUE) >= 2:
                start_match(MATCHMAKING_QUEUE.pop(0), MATCHMAKING_QUEUE.pop(0))
    except Exception as e:
        report_error(e, 'find-match', selected_char_ids)


def start_match(p1, p2):
    """Creates a match for two queued players (caller holds MATCHMAKING_LOCK). All or nothing:
    if any part fails, no trace of the match stays behind and both players are told."""
    room_id = str(uuid.uuid4())[:8]
    game = {
        'roomId': room_id,
        'turn': None,
        'winner': None,
        'turn_count': 0,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'players': {
            'p1': {'id': p1['id'], 'user_id': p1['user_id'], 'username': p1['username'],
                   'resources': [], 'status': [], 'team': p1['team']},
            'p2': {'id': p2['id'], 'user_id': p2['user_id'], 'username': p2['username'],
                   'resources': [], 'status': [], 'team': p2['team']}
        },
        'pending_moves': []
    }
    # Server-only (never sent): with this seed + the moves, the match can be replayed exactly.
    seed = game_engine.seed_match(game)
    match_log.info("Match started: room=%s p1=%s(user=%s) team=%s p2=%s(user=%s) team=%s rng_seed=%s", room_id,
                   p1['username'], p1['user_id'], ','.join(c['id'] for c in p1['team']), p2['username'], p2['user_id'],
                   ','.join(c['id'] for c in p2['team']), seed)
    lock = ROOM_LOCKS[room_id] = threading.RLock()  # exists before any event can find the room
    with lock:
        try:
            GAMES[room_id] = game
            for p in (p1, p2):
                SID_ROOM_MAP[p['id']] = room_id
                USER_ROOMS[p['user_id']] = room_id
            for player in game['players'].values():
                player['page'] = page_of(player['user_id'], player['id'])

            join_room(room_id, sid=p1['id'])
            join_room(room_id, sid=p2['id'])

            emit('game-start', {'roomId': room_id, 'role': 'p1'}, to=p1['id'])
            emit('game-start', {'roomId': room_id, 'role': 'p2'}, to=p2['id'])

            game_engine.start_turn(game, 'p1')
            start_turn_clock(game)
            broadcast_state(game)
        except Exception:
            # A half-created match has no turn and no deadline: it would never end, and both
            # players would stay "already in a match" (BE-12).
            GAMES.pop(room_id, None)
            ROOM_LOCKS.pop(room_id, None)   # threads waiting on it re-check GAMES and back off
            socketio.close_room(room_id)
            for p in (p1, p2):
                SID_ROOM_MAP.pop(p['id'], None)
                USER_ROOMS.pop(p['user_id'], None)
                emit('match-status', MATCH_FAILED_MSG, to=p['id'])
                if p['id'] != request.sid:
                    emit('error-msg', SERVER_ERROR_MSG, to=p['id'])
            raise   # find-match logs it with its traceback and tells the searching player
    ensure_turn_timer()


# --- Socket.IO: in-match actions --------------------------------------------
# The acting player's room and role always come from locked_match() (their own
# connection, under the match's lock), never from the payload.

@socketio.on('queue-skill')
def handle_queue(data):
    try:
        require(data, charId=str, skillId=str, targetPlayerKey=str, targetIndex=int)
        with locked_match() as (room_id, game, role):
            # Skill ids are only unique within one character's kit, so the client
            # must say which character acted; queue_move looks up (charId, skillId).
            result = game_engine.queue_move(game, role, data['charId'], data['skillId'],
                                            data['targetPlayerKey'], data['targetIndex'])
            if result and result.get('countered'):
                match_log.info("Counter-trap fired: room=%s role=%s char=%s damage=%s", room_id, role,
                               data['charId'], result['countered'])
                socketio.emit('message', result['message'], to=room_id)
            if game.get('winner'):
                end_game(room_id, game['winner'])
            else:
                broadcast_state(game)
    except Exception as e:
        report_error(e, 'queue-skill', data)

@socketio.on('cancel-skill')
def handle_cancel(data):
    try:
        require(data, charId=str)
        with locked_match() as (room_id, game, role):
            game_engine.cancel_move(game, role, data['charId'])
            broadcast_state(game)
    except Exception as e:
        report_error(e, 'cancel-skill', data)

@socketio.on('commit-turn')
def handle_commit(data):
    try:
        require(data, paymentList=list)
        with locked_match() as (room_id, game, role):
            if role != game['turn']:
                raise GameError("Not your turn!")
            moves = ' '.join(f"{m['charId']}:{m['skillId']}>{m['targetPid']}{m['targetIndex']}"
                             for m in game['pending_moves']) or '-'
            game_engine.resolve_turn(game, data['paymentList'])
            match_log.info("Turn: room=%s turn=%s role=%s user=%s moves=[%s] ki_paid=%d", room_id,
                           game.get('turn_count'), role, game['players'][role]['user_id'], moves,
                           len(data['paymentList']))
            if game.get('winner'):
                end_game(room_id, game['winner'])
            else:
                start_turn_clock(game)
                broadcast_state(game)
    except Exception as e:
        report_error(e, 'commit-turn', data)

@socketio.on('surrender')
def handle_surrender(data=None):
    """Ends the match as a loss for whoever sends it (any time, any turn).
    There's nothing in the payload to validate; it's ignored."""
    try:
        with locked_match() as (room_id, game, role):
            game_engine.surrender(game, role)
            end_game(room_id, game['winner'],
                     reason=f"{role.upper()} SURRENDERED. {game['winner'].upper()} WINS!", cause='surrender')
    except Exception as e:
        report_error(e, 'surrender')

if __name__ == '__main__':
    # Local development runner only -- production runs under gunicorn (see
    # docs/DEPLOY_PLAN.md). allow_unsafe_werkzeug lets it also start without
    # a terminal attached (e.g. from the browser tests).
    log.info("Development server listening on port %d (production runs gunicorn: see the Dockerfile)", settings.port)
    socketio.run(app, host='0.0.0.0', port=settings.port, allow_unsafe_werkzeug=True)
