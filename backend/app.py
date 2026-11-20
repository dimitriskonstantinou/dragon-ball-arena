from flask import Flask, request, send_from_directory, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import copy
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager

import content_loader
import game_engine
from game_engine import GameError
from models import db, User, UserStats, Character, UserCharacter, Match

log = logging.getLogger(__name__)

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.normpath(os.path.join(BASE_DIR, '..', 'frontend'))

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'game.db')}")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")

GAMES = {}
MATCHMAKING_QUEUE = []
SID_ROOM_MAP = {}  # sid -> roomId, for O(1) disconnect/forfeit lookup

# The server runs every Socket.IO event in its own thread, so shared state needs
# locks. Lock order is always MATCHMAKING_LOCK -> a room lock, never the reverse.
ROOM_LOCKS = {}                        # room_id -> RLock, one per live match (see locked_match)
MATCHMAKING_LOCK = threading.Lock()    # MATCHMAKING_QUEUE + seat checks + creating matches

SERVER_ERROR_MSG = "Something went wrong on the server. Please try again."

# Turn timer (BE-1): every turn has a deadline; one background ticker passes
# expired turns (game_engine.timeout_turn has the rules, incl. forfeit).
TURN_SECONDS = int(os.environ.get('TURN_SECONDS', 60))
TIMER_TICK_SECONDS = 1.0
TURN_TIMER_THREAD = os.environ.get('TURN_TIMER_THREAD', '1') != '0'  # tests drive the timer by hand instead

# Reconnect grace window (BE-2): a player who drops mid-match has this long to
# come back (same account, any tab) before forfeiting. user_id -> room_id.
RECONNECT_SECONDS = int(os.environ.get('RECONNECT_SECONDS', 30))
DISCONNECTED_USERS = {}
_timer_started = False


def now():
    """The server clock for turn deadlines (tests move it by patching time.time)."""
    return time.time()


def report_error(e, event):
    """GameErrors are rule violations -- tell the player. Anything else is a
    bug: log the full traceback and don't leak internals to the client."""
    if isinstance(e, GameError):
        emit('error-msg', str(e), to=request.sid)
    else:
        log.exception("Unhandled error in %s", event)
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


def ensure_db_ready():
    """Creates missing tables and syncs the character registry. No manual
    reseed is ever needed after editing content files."""
    with app.app_context():
        db.create_all()
        added, updated = sync_character_registry()
        if added or updated:
            log.info("Character registry synced: %d added, %d updated", added, updated)


ensure_db_ready()


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db.session.get(User, uid)


def unlocked_character_ids(user):
    """TEMP unlock policy until missions exist (see the Mission models):
    every account has every active character -- including ones added after
    it registered -- with no DB query. Replace this when unlocks are built."""
    return list(CATALOG)


def characters_for_user(user, base_url):
    """Fresh copies of this account's characters, ready for a match, with
    image paths turned into absolute URLs for however the client reached this
    server. Never modifies the shared catalog."""
    result = {}

    def skill_urls(effects):
        # Images swapped in later by prime_skill (e.g. Puar -> Spirit Ball) need
        # the same URL as regular skill images, or the browser 404s on them.
        for effect in effects:
            if effect.get('primed_image'):
                effect['primed_image'] = base_url + 'photos/skills/' + effect['primed_image']
            skill_urls(effect.get('primed_effects', []))

    for cid in unlocked_character_ids(user):
        char_dict = copy.deepcopy(CATALOG[cid])
        char_dict['defense'] = 0
        char_dict['image'] = base_url + 'photos/' + char_dict['image']
        for skill in char_dict['skills']:
            if skill.get('image'):
                skill['image'] = base_url + 'photos/skills/' + skill['image']
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

    winner_uid = game['players'][winner_role].get('user_id') if winner_role else None
    started_at_raw = game.get('started_at')
    started_at = datetime.fromisoformat(started_at_raw) if started_at_raw else datetime.now(timezone.utc)

    db.session.add(Match(player1_id=p1_uid, player2_id=p2_uid, winner_id=winner_uid,
                          started_at=started_at, ended_at=datetime.now(timezone.utc)))

    for uid, won in ((p1_uid, winner_uid == p1_uid), (p2_uid, winner_uid == p2_uid)):
        stats = db.session.get(UserStats, uid)
        if stats:
            stats.record_result(won)

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
                log.exception("Turn timeout failed: room=%s", room_id)
                continue
            if game.get('winner'):
                reason = None
                if strikes >= game_engine.TIMEOUTS_TO_FORFEIT:
                    reason = (f"{timed_out.upper()} RAN OUT OF TIME {strikes} TURNS IN A ROW AND FORFEITS. "
                              f"{game['winner'].upper()} WINS!")
                end_game(room_id, game['winner'], reason=reason)
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
            end_game(room_id, winner, reason=f"{loser.upper()} DIDN'T COME BACK IN TIME. {winner.upper()} WINS!")


def turn_timer_loop():
    while True:
        socketio.sleep(TIMER_TICK_SECONDS)
        try:
            with app.app_context():
                check_turn_timers()
                check_disconnect_timers()
        except Exception:
            log.exception("Turn timer loop error")


def ensure_turn_timer():
    """Starts the single ticker on the first match (caller holds MATCHMAKING_LOCK)."""
    global _timer_started
    if TURN_TIMER_THREAD and not _timer_started:
        _timer_started = True
        socketio.start_background_task(turn_timer_loop)

def end_game(room_id, winner, reason=None):
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
    game['winner'] = winner
    for p_key in ('p1', 'p2'):
        SID_ROOM_MAP.pop(game['players'][p_key]['id'], None)
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
    message = f"GAME OVER! {winner.upper()} WINS!" if not reason else reason
    socketio.emit('message', message, to=room_id)
    socketio.close_room(room_id)


# --- static file / photo serving --------------------------------------------

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

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not username or not email or not password:
        return jsonify({'error': 'username, email and password are required'}), 400
    if not (3 <= len(username) <= 20):
        return jsonify({'error': 'username must be 3-20 characters'}), 400
    if len(password) < 6:
        return jsonify({'error': 'password must be at least 6 characters'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'username already taken'}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'email already registered'}), 409

    user = User(username=username, email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.flush()  # assigns user.id, needed by the rows below

    db.session.add(UserStats(user_id=user.id))

    # Unlock rows are recorded for the future mission system; today access is
    # decided by unlocked_character_ids() (every active character).
    for cid in CATALOG:
        db.session.add(UserCharacter(user_id=user.id, character_id=cid))

    db.session.commit()

    session['user_id'] = user.id
    return jsonify(user.to_dict()), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'invalid username or password'}), 401

    session['user_id'] = user.id
    return jsonify(user.to_dict())

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({'ok': True})

@app.route('/api/me')
def me():
    user = current_user()
    if not user:
        return jsonify({'error': 'not logged in'}), 401
    return jsonify(user.to_dict())


# --- Socket.IO: lobby / matchmaking -----------------------------------------

@socketio.on('connect')
def handle_connect():
    user = current_user()
    if not user:
        emit('auth-required')
        return
    # Display fields only: skill mechanics stay server-side (same rule as view_for).
    char_list = [game_engine.strip_skill_internals(c) for c in characters_for_user(user, request.host_url).values()]
    emit('character-list', char_list)
    rejoin_match(user)


def rejoin_match(user):
    """If this account dropped out of a match that is still waiting for it
    (reload, new tab, network switch), attach this new connection to it and
    send the current state. Returns True if it rejoined."""
    room_id = DISCONNECTED_USERS.get(user.id)
    lock = ROOM_LOCKS.get(room_id)
    if lock is None:
        return False
    with lock:
        game = GAMES.get(room_id)
        if game is None or game.get('winner') or DISCONNECTED_USERS.get(user.id) != room_id:
            return False
        role = next(r for r in ('p1', 'p2') if game['players'][r]['user_id'] == user.id)
        player = game['players'][role]
        player['id'] = request.sid
        player['disconnected_at'] = None
        DISCONNECTED_USERS.pop(user.id, None)
        SID_ROOM_MAP[request.sid] = room_id
        join_room(room_id)
        emit('game-start', {'roomId': room_id, 'role': role})
        socketio.emit('message', f"{role.upper()} RECONNECTED.", to=room_id)
        broadcast_state(game)
        return True

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid

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
        # Not a forfeit yet: the match waits RECONNECT_SECONDS for this account to
        # come back (rejoin_match); check_disconnect_timers forfeits it after that.
        game['players'][role]['disconnected_at'] = now()
        DISCONNECTED_USERS[game['players'][role]['user_id']] = room_id
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

        available_chars = characters_for_user(user, request.host_url)
        my_team = [copy.deepcopy(available_chars[c]) for c in selected_char_ids if c in available_chars]
        if len(my_team) != 3:
            raise GameError("One or more selected characters aren't unlocked on this account!")

        # Seat checks + joining the queue + pairing are one atomic step, or two
        # tabs of the same account could both pass the checks at once.
        with MATCHMAKING_LOCK:
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
            emit('match-status', "Searching for opponent...")
            if len(MATCHMAKING_QUEUE) >= 2:
                start_match(MATCHMAKING_QUEUE.pop(0), MATCHMAKING_QUEUE.pop(0))
    except Exception as e:
        report_error(e, 'find-match')


def start_match(p1, p2):
    """Creates a match for two queued players (caller holds MATCHMAKING_LOCK)."""
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
    lock = ROOM_LOCKS[room_id] = threading.RLock()  # exists before any event can find the room
    with lock:
        GAMES[room_id] = game
        SID_ROOM_MAP[p1['id']] = room_id
        SID_ROOM_MAP[p2['id']] = room_id

        join_room(room_id, sid=p1['id'])
        join_room(room_id, sid=p2['id'])

        emit('game-start', {'roomId': room_id, 'role': 'p1'}, to=p1['id'])
        emit('game-start', {'roomId': room_id, 'role': 'p2'}, to=p2['id'])

        game_engine.start_turn(game, 'p1')
        start_turn_clock(game)
        broadcast_state(game)
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
                socketio.emit('message', result['message'], to=room_id)
            if game.get('winner'):
                end_game(room_id, game['winner'])
            else:
                broadcast_state(game)
    except Exception as e:
        report_error(e, 'queue-skill')

@socketio.on('cancel-skill')
def handle_cancel(data):
    try:
        require(data, charId=str)
        with locked_match() as (room_id, game, role):
            game_engine.cancel_move(game, role, data['charId'])
            broadcast_state(game)
    except Exception as e:
        report_error(e, 'cancel-skill')

@socketio.on('commit-turn')
def handle_commit(data):
    try:
        require(data, paymentList=list)
        with locked_match() as (room_id, game, role):
            if role != game['turn']:
                raise GameError("Not your turn!")
            game_engine.resolve_turn(game, data['paymentList'])
            if game.get('winner'):
                end_game(room_id, game['winner'])
            else:
                start_turn_clock(game)
                broadcast_state(game)
    except Exception as e:
        report_error(e, 'commit-turn')

if __name__ == '__main__':
    # Local development runner only -- production runs under gunicorn (see
    # docs/DEPLOY_PLAN.md). allow_unsafe_werkzeug lets it also start without
    # a terminal attached (e.g. from the browser tests).
    logging.basicConfig(level=logging.INFO)
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), allow_unsafe_werkzeug=True)
