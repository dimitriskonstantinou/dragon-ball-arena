from flask import Flask, request, send_from_directory, session, jsonify
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import copy
import json
import os
import uuid

import characters
import game_engine
from models import db, User, UserStats, Character, UserCharacter, Match

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


def ensure_db_ready():
    """Creates tables if missing, and seeds the characters table from the
    legacy characters.py roster on a completely fresh database. For
    re-seeding after editing characters.py, use seed_db.py instead (it
    upserts rather than only running once)."""
    with app.app_context():
        db.create_all()
        if Character.query.count() == 0:
            for char_id, char in characters.CHARACTERS.items():
                db.session.add(Character(
                    id=char_id, name=char['name'], image=char['image'],
                    health=char['health'], skills_json=json.dumps(char['skills']),
                    is_starter=True,
                ))
            db.session.commit()
            print(f"Auto-seeded {len(characters.CHARACTERS)} characters into a fresh database.")


ensure_db_ready()


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    return db.session.get(User, uid)


def characters_for_user(user, base_url):
    """Characters this account has unlocked, with 'image' rewritten to an
    absolute URL based on however the client actually reached this server
    (host/port/scheme), instead of a value hardcoded at authoring time."""
    unlocked_ids = [uc.character_id for uc in user.unlocked_characters]
    if not unlocked_ids:
        return {}
    result = {}
    for row in Character.query.filter(Character.id.in_(unlocked_ids)).all():
        char_dict = row.to_game_dict()
        char_dict['image'] = base_url + 'photos/' + char_dict['image']
        for skill in char_dict['skills']:
            if skill.get('image'):
                skill['image'] = base_url + 'photos/skills/' + skill['image']
        result[row.id] = char_dict
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


ENDED_ROOMS = set()

def end_game(room_id, winner, reason=None):
    game = GAMES.get(room_id)
    # NOTE: game_engine.resolve_turn() sets game['winner'] itself the moment
    # a team is wiped, *before* this function ever runs -- so "winner is
    # already set" can't be used to detect "this room was already cleaned
    # up," or this whole function would always no-op on the normal (combat)
    # win path and only ever work for the disconnect path. Track completion
    # separately instead.
    if not game or room_id in ENDED_ROOMS:
        return
    ENDED_ROOMS.add(room_id)
    game['winner'] = winner
    for p_key in ('p1', 'p2'):
        sid = game['players'][p_key]['id']
        SID_ROOM_MAP.pop(sid, None)

    persist_match_result(game, winner)

    socketio.emit('update-state', game, to=room_id)
    message = f"GAME OVER! {winner.upper()} WINS!" if not reason else reason
    socketio.emit('message', message, to=room_id)


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

    # TEMP: every new account gets every character that currently exists,
    # because the mission-based unlock system isn't built yet -- see the
    # Mission/UserMissionProgress models and the README for what's still
    # undecided there. Revisit this loop once that's designed.
    for char in Character.query.all():
        db.session.add(UserCharacter(user_id=user.id, character_id=char.id))

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
    char_list = list(characters_for_user(user, request.host_url).values())
    emit('character-list', char_list)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid

    global MATCHMAKING_QUEUE
    MATCHMAKING_QUEUE = [p for p in MATCHMAKING_QUEUE if p['id'] != sid]

    room_id = SID_ROOM_MAP.pop(sid, None)
    if not room_id:
        return
    game = GAMES.get(room_id)
    if not game or game.get('winner'):
        return

    if game['players']['p1']['id'] == sid:
        winner = 'p2'
    elif game['players']['p2']['id'] == sid:
        winner = 'p1'
    else:
        return

    end_game(room_id, winner, reason="OPPONENT DISCONNECTED! " + winner.upper() + " WINS!")

@socketio.on('find-match')
def handle_find_match(selected_char_ids):
    sid = request.sid
    user = current_user()
    if not user:
        emit('error-msg', "You must be logged in to find a match!")
        return

    if sid in SID_ROOM_MAP:
        emit('error-msg', "You are already in a match!")
        return
    if any(p['id'] == sid for p in MATCHMAKING_QUEUE):
        emit('error-msg', "You are already searching for a match!")
        return
    if len(selected_char_ids) != 3:
        emit('error-msg', "You must select exactly 3 characters!")
        return

    available_chars = characters_for_user(user, request.host_url)
    my_team = []
    for char_id in selected_char_ids:
        if char_id in available_chars:
            my_team.append(copy.deepcopy(available_chars[char_id]))

    if len(my_team) != 3:
        emit('error-msg', "One or more selected characters aren't unlocked on this account!")
        return

    player_entry = {'id': sid, 'user_id': user.id, 'username': user.username, 'team': my_team}
    MATCHMAKING_QUEUE.append(player_entry)

    emit('match-status', "Searching for opponent...")

    if len(MATCHMAKING_QUEUE) >= 2:
        p1 = MATCHMAKING_QUEUE.pop(0)
        p2 = MATCHMAKING_QUEUE.pop(0)

        room_id = str(uuid.uuid4())[:8]

        # Initialize Game with turn_count = 0
        GAMES[room_id] = {
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
        SID_ROOM_MAP[p1['id']] = room_id
        SID_ROOM_MAP[p2['id']] = room_id

        join_room(room_id, sid=p1['id'])
        join_room(room_id, sid=p2['id'])

        emit('game-start', {'roomId': room_id, 'role': 'p1'}, to=p1['id'])
        emit('game-start', {'roomId': room_id, 'role': 'p2'}, to=p2['id'])

        game = GAMES[room_id]
        game_engine.start_turn(game, 'p1')

        socketio.emit('update-state', game, to=room_id)


# --- Socket.IO: in-match actions --------------------------------------------

@socketio.on('queue-skill')
def handle_queue(data):
    room_id = data.get('roomId')
    if room_id in GAMES:
        game = GAMES[room_id]
        try:
            my_player_key = data['myPlayerKey']
            if game['players'].get(my_player_key, {}).get('id') != request.sid:
                raise Exception("Not authorized for this player slot!")

            # --- FIX: Explicitly find the character ID here ---
            player = game['players'][my_player_key]
            char_id = None
            for char in player['team']:
                for s in char['skills']:
                    if s['id'] == data['skillId']:
                        char_id = char['id']
                        break
                if char_id: break

            if not char_id:
                raise Exception("Character not found for this skill!")

            game_engine.queue_move(
                game,
                my_player_key,
                char_id, # Pass the found ID explicitly
                data['skillId'],
                data['targetPlayerKey'],
                data['targetIndex']
            )
            emit('update-state', game, to=room_id)
        except Exception as e:
            print(f"Error in queue-skill: {e}") # Print to server console for debugging
            emit('error-msg', str(e), to=request.sid)

@socketio.on('cancel-skill')
def handle_cancel(data):
    room_id = data.get('roomId')
    if room_id in GAMES:
        game = GAMES[room_id]
        my_player_key = data['myPlayerKey']
        if game['players'].get(my_player_key, {}).get('id') != request.sid:
            emit('error-msg', "Not authorized for this player slot!", to=request.sid)
            return
        game_engine.cancel_move(game, my_player_key, data['charId'])
        emit('update-state', game, to=room_id)

@socketio.on('commit-turn')
def handle_commit(data):
    room_id = data.get('roomId')
    payment_list = data.get('paymentList')

    if room_id in GAMES:
        game = GAMES[room_id]
        if game.get('winner'): return

        sender_role = None
        if game['players'].get('p1') and game['players']['p1']['id'] == request.sid: sender_role = 'p1'
        elif game['players'].get('p2') and game['players']['p2']['id'] == request.sid: sender_role = 'p2'

        if sender_role == game['turn']:
            try:
                game_engine.resolve_turn(game, payment_list)
                if game.get('winner'):
                    end_game(room_id, game['winner'])
                else:
                    emit('update-state', game, to=room_id)
            except Exception as e:
                emit('error-msg', str(e), to=request.sid)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
