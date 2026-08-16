"""
End-to-end smoke test that drives app.py's real HTTP + Socket.IO handlers
(via Flask's test client and Flask-SocketIO's in-process test client -- no
real network/port needed) to make sure the full stack works together:

  register -> login (session cookie) -> Socket.IO connect (auth-gated) ->
  find-match -> queue-skill -> commit-turn -> match ends -> stats persisted

This exercises real HTTP requests against real SQLite-backed models, so it
also proves the DB layer (accounts, unlocked characters, match history,
win/loss streaks) works, not just the in-memory game engine.

Run with: python test_integration_smoke.py

NOTE: this hits the real dev database (backend/game.db) -- it registers two
throwaway accounts with a random suffix each run so re-running never
collides with previous runs, but it does leave a couple of harmless rows
behind. That's an acceptable tradeoff for an integration smoke test whose
whole point is exercising the real stack, not a hermetic unit test.
"""
import uuid

import app as appmod

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"FAIL: {name}  {detail}")


def register(flask_client, username, email, password='testpass123'):
    return flask_client.post('/api/register', json={
        'username': username, 'email': email, 'password': password
    })


suffix = uuid.uuid4().hex[:8]
flask_client1 = appmod.app.test_client()
flask_client2 = appmod.app.test_client()

r1 = register(flask_client1, f'vegeta_{suffix}', f'vegeta_{suffix}@test.local')
r2 = register(flask_client2, f'goku_{suffix}', f'goku_{suffix}@test.local')
check("player 1 registers successfully", r1.status_code == 201, r1.get_json())
check("player 2 registers successfully", r2.status_code == 201, r2.get_json())
user1_id = r1.get_json().get('id')
user2_id = r2.get_json().get('id')

dup = register(flask_client1, f'vegeta_{suffix}', f'someone-else@test.local')
check("registering a duplicate username is rejected", dup.status_code == 409, dup.get_json())

bad_login = flask_client1.post('/api/login', json={'username': f'vegeta_{suffix}', 'password': 'wrong'})
check("logging in with the wrong password is rejected", bad_login.status_code == 401, bad_login.get_json())

# The SocketIO test client shares its Flask test client's cookie jar, so the
# session cookie set by /api/register above carries into the Socket.IO
# handshake -- this is what lets handle_connect() resolve current_user().
client1 = appmod.socketio.test_client(appmod.app, flask_test_client=flask_client1)
client2 = appmod.socketio.test_client(appmod.app, flask_test_client=flask_client2)

initial1 = client1.get_received()
client2.get_received()

char_list_event = next((e for e in initial1 if e['name'] == 'character-list'), None)
check("authenticated connect receives this account's unlocked characters",
      char_list_event is not None and len(char_list_event['args'][0]) == 10,
      char_list_event)

# Pick Vegeta (has the new shield skill) and Krillin (has the new cleanse skill)
client1.emit('find-match', ['vegeta', 'krillin', 'gohan'])
client2.emit('find-match', ['goku_saiyan_saga', 'piccolo', 'cell'])

r1_events = client1.get_received()
r2_events = client2.get_received()

game_start_1 = next((e for e in r1_events if e['name'] == 'game-start'), None)
game_start_2 = next((e for e in r2_events if e['name'] == 'game-start'), None)
check("both clients receive game-start", game_start_1 is not None and game_start_2 is not None)

room_id = game_start_1['args'][0]['roomId']
role1 = game_start_1['args'][0]['role']
role2 = game_start_2['args'][0]['role']
check("clients got opposite roles", {role1, role2} == {'p1', 'p2'})

update = next((e for e in r1_events if e['name'] == 'update-state'), None)
check("initial update-state received", update is not None)
state = update['args'][0]
vegeta = next(c for c in state['players'][role1]['team'] if c['id'] == 'vegeta')
check("character image URL is absolute and host-derived (not a stale hardcoded value)",
      vegeta['image'].endswith('/photos/Vegeta.png') and vegeta['image'].startswith('http'),
      vegeta['image'])

p1_client, p1_role = (client1, role1) if role1 == 'p1' else (client2, role2)
p2_client, p2_role = (client1, role1) if role1 == 'p2' else (client2, role2)

game = appmod.GAMES[room_id]
check("game state records each player's account id (not just their socket)",
      game['players']['p1'].get('user_id') is not None and game['players']['p2'].get('user_id') is not None,
      (game['players']['p1'].get('user_id'), game['players']['p2'].get('user_id')))

# Give p1 resources deterministically instead of relying on the random dice
# roll, so this test is not flaky.
game['players']['p1']['resources'] = ['martial', 'energy', 'spirit', 'rage']
game['players']['p2']['resources'] = ['martial', 'energy', 'spirit', 'rage']

# Vegeta's "Giant Crush" costs 1 martial, damages the enemy and shields self.
vegeta_owner_client = p1_client if any(c['id'] == 'vegeta' for c in game['players']['p1']['team']) else p2_client
vegeta_role = 'p1' if vegeta_owner_client is p1_client else 'p2'
enemy_role = 'p2' if vegeta_role == 'p1' else 'p1'
enemy_client = p2_client if vegeta_owner_client is p1_client else p1_client

game['turn'] = vegeta_role
vegeta_owner_client.get_received()
vegeta_owner_client.emit('queue-skill', {
    'roomId': room_id, 'skillId': 'ozaru_crush', 'myPlayerKey': vegeta_role,
    'targetPlayerKey': enemy_role, 'targetIndex': 0
})
received = vegeta_owner_client.get_received()
errors = [e for e in received if e['name'] == 'error-msg']
check("queueing Giant Crush produces no error", errors == [], errors)

vegeta_owner_client.emit('commit-turn', {'roomId': room_id, 'paymentList': ['martial']})
received = vegeta_owner_client.get_received()
update = next((e for e in received if e['name'] == 'update-state'), None)
check("commit-turn resolves and broadcasts update-state", update is not None)

vegeta_after = next(c for c in game['players'][vegeta_role]['team'] if c['id'] == 'vegeta')
check("Vegeta gained a destructible defense shield from Giant Crush",
      vegeta_after.get('defense', 0) == 20, vegeta_after.get('defense'))

enemy_first = game['players'][enemy_role]['team'][0]
check("enemy target took Giant Crush's damage", enemy_first['health'] == 80, enemy_first['health'])

# --- Force the match to a decisive end so we can check DB persistence -------
# (turn auto-advanced to the enemy after the commit above)
for c in game['players'][enemy_role]['team']:
    c['health'] = 0
enemy_client.get_received()
enemy_client.emit('commit-turn', {'roomId': room_id, 'paymentList': []})
received = enemy_client.get_received()
check("wiping a team's HP and committing ends the match",
      game.get('winner') == vegeta_role, game.get('winner'))

winner_uid = game['players'][vegeta_role]['user_id']
loser_uid = game['players'][enemy_role]['user_id']

with appmod.app.app_context():
    winner_stats = appmod.db.session.get(appmod.UserStats, winner_uid)
    loser_stats = appmod.db.session.get(appmod.UserStats, loser_uid)
    check("winner's stats recorded exactly one win",
          winner_stats.total_wins == 1 and winner_stats.total_matches == 1 and winner_stats.current_win_streak == 1,
          (winner_stats.total_wins, winner_stats.total_matches, winner_stats.current_win_streak))
    check("loser's stats recorded exactly one loss",
          loser_stats.total_losses == 1 and loser_stats.total_matches == 1 and loser_stats.current_win_streak == 0,
          (loser_stats.total_losses, loser_stats.total_matches, loser_stats.current_win_streak))

    match_row = appmod.Match.query.filter_by(winner_id=winner_uid).order_by(appmod.Match.id.desc()).first()
    check("a Match row was created for this game",
          match_row is not None and {match_row.player1_id, match_row.player2_id} == {winner_uid, loser_uid},
          match_row)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    raise SystemExit(1)
else:
    print("Integration smoke test passed: register -> login -> find-match -> queue-skill -> "
          "commit-turn -> match end all work through the real stack, and stats/match history "
          "were correctly persisted to the database.")
