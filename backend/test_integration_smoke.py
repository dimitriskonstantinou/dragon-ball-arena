"""
End-to-end smoke test that drives app.py's real HTTP + Socket.IO handlers
(via Flask's test client and Flask-SocketIO's in-process test client -- no
real network/port needed) to make sure the full stack works together:

  register -> login (session cookie) -> Socket.IO connect (auth-gated) ->
  find-match -> queue-skill -> commit-turn -> match ends -> stats persisted

This exercises real HTTP requests against real SQLite-backed models, so it
also proves the DB layer (accounts, unlocked characters, match history,
win/loss streaks) works, not just the in-memory game engine.

Deliberately roster-agnostic: it picks whatever characters currently exist
in the DB rather than hardcoding names/skill ids, and only exercises the
generic "does the pipeline work" shape (skill goes on cooldown, match ends,
stats persist) rather than specific skill math -- that level of detail is
covered by test_game_engine.py against real character data instead. The
roster is being rebuilt from scratch one character at a time, so this test
needs to keep working whether there's 1 character or 50.

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


def resources_for_cost(cost):
    """Enough dice to pay a skill's cost exactly (any type covers 'random')."""
    dice = [t for t, amt in cost.items() if t != 'random' for _ in range(amt)]
    filler_type = dice[0] if dice else 'energy'
    dice += [filler_type] * cost.get('random', 0)
    return dice


suffix = uuid.uuid4().hex[:8]
flask_client1 = appmod.app.test_client()
flask_client2 = appmod.app.test_client()

r1 = register(flask_client1, f'p1_{suffix}', f'p1_{suffix}@test.local')
r2 = register(flask_client2, f'p2_{suffix}', f'p2_{suffix}@test.local')
check("player 1 registers successfully", r1.status_code == 201, r1.get_json())
check("player 2 registers successfully", r2.status_code == 201, r2.get_json())

dup = register(flask_client1, f'p1_{suffix}', f'someone-else@test.local')
check("registering a duplicate username is rejected", dup.status_code == 409, dup.get_json())

bad_login = flask_client1.post('/api/login', json={'username': f'p1_{suffix}', 'password': 'wrong'})
check("logging in with the wrong password is rejected", bad_login.status_code == 401, bad_login.get_json())

# The SocketIO test client shares its Flask test client's cookie jar, so the
# session cookie set by /api/register above carries into the Socket.IO
# handshake -- this is what lets handle_connect() resolve current_user().
client1 = appmod.socketio.test_client(appmod.app, flask_test_client=flask_client1)
client2 = appmod.socketio.test_client(appmod.app, flask_test_client=flask_client2)

initial1 = client1.get_received()
client2.get_received()

char_list_event = next((e for e in initial1 if e['name'] == 'character-list'), None)
check("authenticated connect receives a character list", char_list_event is not None, char_list_event)
available = char_list_event['args'][0] if char_list_event else []

with appmod.app.app_context():
    db_count = appmod.Character.query.count()
check("character-list matches what's actually seeded in the DB", len(available) == db_count,
      (len(available), db_count))

if len(available) < 3:
    print(f"\nSKIPPED: matchmaking/combat/persistence checks need >= 3 characters in the roster "
          f"(currently {len(available)}). Re-run once more characters are added.")
else:
    team_ids = [c['id'] for c in available[:3]]

    client1.emit('find-match', team_ids)
    client2.emit('find-match', team_ids)

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
    any_char = state['players'][role1]['team'][0]
    check("character image URL is absolute and host-derived (not a stale hardcoded value)",
          any_char['image'].startswith('http') and '/photos/' in any_char['image'], any_char['image'])

    p1_client = client1 if role1 == 'p1' else client2
    p2_client = client2 if role1 == 'p1' else client1

    game = appmod.GAMES[room_id]
    check("game state records each player's account id (not just their socket)",
          game['players']['p1'].get('user_id') is not None and game['players']['p2'].get('user_id') is not None,
          (game['players']['p1'].get('user_id'), game['players']['p2'].get('user_id')))

    actor = game['players']['p1']['team'][0]
    skill = actor['skills'][0]
    game['players']['p1']['resources'] = resources_for_cost(skill['cost'])
    game['turn'] = 'p1'

    p1_client.get_received()
    p2_client.get_received()
    p1_client.emit('queue-skill', {
        'roomId': room_id, 'charId': actor['id'], 'skillId': skill['id'], 'myPlayerKey': 'p1',
        'targetPlayerKey': 'p2', 'targetIndex': 0
    })
    received = p1_client.get_received()
    errors = [e for e in received if e['name'] == 'error-msg']
    check(f"queueing {actor['name']}'s {skill['name']} produces no error", errors == [], errors)

    # Regression: the raw state (live queue, socket ids) used to go to both players.
    p1_update = next((e['args'][0] for e in reversed(received) if e['name'] == 'update-state'), None)
    p2_update = next((e['args'][0] for e in reversed(p2_client.get_received()) if e['name'] == 'update-state'), None)
    check("the queueing player's own view shows their queued move",
          p1_update is not None and len(p1_update['pending_moves']) == 1, p1_update and p1_update['pending_moves'])
    check("the opponent's view does NOT show that queued move",
          p2_update is not None and p2_update['pending_moves'] == [], p2_update and p2_update['pending_moves'])
    check("no socket ids or account ids are sent to clients",
          all(f not in p for u in (p1_update, p2_update) if u for p in u['players'].values() for f in ('id', 'user_id')))

    # Regression: an empty payment used to cast costed skills for free.
    if skill['cost']:
        p1_client.emit('commit-turn', {'roomId': room_id, 'paymentList': []})
        received = p1_client.get_received()
        check("commit-turn with an empty payment for a costed skill is rejected",
              any(e['name'] == 'error-msg' for e in received) and skill['currentCooldown'] == 0,
              (received, skill['currentCooldown']))

    p1_client.emit('commit-turn', {'roomId': room_id, 'paymentList': list(game['players']['p1']['resources'])})
    received = p1_client.get_received()
    update = next((e for e in received if e['name'] == 'update-state'), None)
    check("commit-turn resolves and broadcasts update-state", update is not None)
    check("the used skill went on cooldown (proof the engine actually processed it)",
          skill['currentCooldown'] > 0, skill['currentCooldown'])

    # --- Regression test: skill ids are only unique within one character's
    # own kit (e.g. every character's universal defensive skill shares the
    # id "afterimage_technique") -- queueing must resolve to the character
    # whose button was actually clicked, not silently the first team member
    # found with a matching skill id. This was a real bug: clicking
    # Piccolo's or Raditz's "Block" fired Goku's "Afterimage Technique"
    # instead, whenever Goku happened to be listed first on the team. ---
    team_members = game['players']['p1']['team']
    shared = None
    for i, c1 in enumerate(team_members):
        for c2 in team_members[i + 1:]:
            common = set(s['id'] for s in c1['skills']) & set(s['id'] for s in c2['skills'])
            if common:
                shared = (c2, next(iter(common)))  # c2: NOT the first team member, to prove it's not just picking index 0
                break
        if shared:
            break

    if not shared:
        print(f"\nSKIPPED: shared-skill-id regression check needs 2 team members sharing a skill id "
              f"(team: {[c['id'] for c in team_members]}).")
    else:
        other_char, shared_skill_id = shared
        other_skill = next(s for s in other_char['skills'] if s['id'] == shared_skill_id)
        other_index = team_members.index(other_char)

        game['turn'] = 'p1'
        game['players']['p1']['resources'] = resources_for_cost(other_skill['cost'])
        p1_client.get_received()
        p1_client.emit('queue-skill', {
            'roomId': room_id, 'charId': other_char['id'], 'skillId': shared_skill_id,
            'myPlayerKey': 'p1', 'targetPlayerKey': 'p1', 'targetIndex': other_index
        })
        received = p1_client.get_received()
        errors = [e for e in received if e['name'] == 'error-msg']
        check(f"queueing {other_char['name']}'s shared skill '{shared_skill_id}' produces no error",
              errors == [], errors)

        p1_client.emit('commit-turn', {'roomId': room_id, 'paymentList': list(game['players']['p1']['resources'])})
        p1_client.get_received()
        check(f"the shared skill went on cooldown for {other_char['name']} specifically "
              f"(not silently the first team member with that skill id)",
              other_skill['currentCooldown'] > 0, (other_char['id'], other_skill['currentCooldown']))

        first_member_skill = next((s for s in team_members[0]['skills'] if s['id'] == shared_skill_id), None)
        if team_members[0]['id'] != other_char['id'] and first_member_skill:
            check(f"the first team member's own copy of the shared skill was untouched",
                  first_member_skill['currentCooldown'] == 0, first_member_skill['currentCooldown'])

    # --- Force the match to a decisive end so we can check DB persistence ---
    # (turn auto-advanced to p2 after the commit above)
    for c in game['players']['p2']['team']:
        c['health'] = 0
    p2_client.get_received()
    p2_client.emit('commit-turn', {'roomId': room_id, 'paymentList': []})
    p2_client.get_received()
    check("wiping a team's HP and committing ends the match", game.get('winner') == 'p1', game.get('winner'))

    winner_uid = game['players']['p1']['user_id']
    loser_uid = game['players']['p2']['user_id']

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
    print("Integration smoke test passed.")
