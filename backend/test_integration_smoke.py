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


def all_image_urls(char):
    """Every image URL in a character, including ones prime_skill swaps in later."""
    def walk(effects):
        for e in effects:
            if e.get('primed_image'):
                yield e['primed_image']
            yield from walk(e.get('primed_effects', []))
    yield char['image']
    for s in char['skills']:
        if s.get('image'):
            yield s['image']
        yield from walk(s.get('effects', []))


with appmod.app.app_context():
    user1 = appmod.User.query.filter_by(username=f'p1_{suffix}').first()
    server_side = appmod.characters_for_user(user1, 'http://localhost/')

# Regression: primed_image (e.g. Yamcha's Spirit Ball icon) used to be sent as a
# bare filename, so the browser 404'd on it (found by the Playwright test).
# Checked on the server-side team data, which still carries the effects.
urls = [u for c in server_side.values() for u in all_image_urls(c)]
relative = [u for u in urls if not u.startswith('http')]
check("every image URL in match teams is absolute, including primed skill images",
      relative == [] and any('SpiritBall' in u for u in urls) == ('yamcha_saiyan_saga' in server_side), relative)

# --- Step 12b: the roster comes from the in-memory content catalog ---
catalog = appmod.CATALOG
check("character-list offers exactly the active content catalog, in order",
      [c['id'] for c in available] == list(catalog), ([c['id'] for c in available], list(catalog)))
check("the lobby list carries display fields only (no skill effects / base_* backups)",
      all(not any(k == 'effects' or k.startswith('base_') for k in s) for c in available for s in c['skills']))
check("building teams never modifies the shared catalog (image paths stay relative)",
      all(not c['image'].startswith('http') for c in catalog.values()))

with appmod.app.app_context():
    registry = {row.id: row for row in appmod.Character.query.all()}
check("the characters table registers every active character automatically (no manual reseed)",
      set(catalog) <= set(registry), set(catalog) - set(registry))
check("the registry holds no stale skills copy", all(row.skills_json == '[]' for row in registry.values()))

# Removing a character from content: it stays registered (accounts may reference
# it) but is no longer offered. Simulated with a reduced catalog.
removed_id = next(iter(catalog))
reduced = {cid: c for cid, c in catalog.items() if cid != removed_id}
real_catalog = appmod.CATALOG
appmod.CATALOG = reduced
try:
    with appmod.app.app_context():
        appmod.sync_character_registry(reduced)
        still_registered = appmod.db.session.get(appmod.Character, removed_id) is not None
        offered = appmod.characters_for_user(user1, 'http://localhost/')
finally:
    appmod.CATALOG = real_catalog
check("a character removed from content stays in the registry (never deleted)", still_registered)
check("...but is no longer offered to players", removed_id not in offered and len(offered) == len(reduced))

# An account created before a character existed still gets it (TEMP all-unlocked policy).
with appmod.app.app_context():
    appmod.UserCharacter.query.filter_by(user_id=user1.id).filter(
        appmod.UserCharacter.character_id != removed_id).delete()
    appmod.db.session.commit()
    check("an older account still gets characters added after it registered",
          list(appmod.characters_for_user(user1, 'http://localhost/')) == list(catalog))

# Connecting no longer reads the characters table (roster comes from memory).
from sqlalchemy import event
statements = []
with appmod.app.app_context():
    sql_engine = appmod.db.engine
listener = lambda conn, cur, stmt, *a: statements.append(stmt.lower())
event.listen(sql_engine, 'before_cursor_execute', listener)
try:
    extra = appmod.socketio.test_client(appmod.app, flask_test_client=flask_client1)
    extra.get_received()
    extra.disconnect()
finally:
    event.remove(sql_engine, 'before_cursor_execute', listener)
reads_characters = [st for st in statements if ' characters' in st and 'user_characters' not in st]
check("connecting doesn't query the characters table", reads_characters == [] and len(statements) <= 1,
      statements)

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
        'charId': actor['id'], 'skillId': skill['id'],
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
    sent_skills = [s for u in (p1_update, p2_update) if u for p in u['players'].values() for c in p['team'] for s in c['skills']]
    check("skill effects are not sent to clients, but name/cost/description are",
          sent_skills and all('effects' not in s and {'name', 'cost', 'description'} <= set(s) for s in sent_skills))

    # Regression: an empty payment used to cast costed skills for free.
    if skill['cost']:
        p1_client.emit('commit-turn', {'paymentList': []})
        received = p1_client.get_received()
        check("commit-turn with an empty payment for a costed skill is rejected",
              any(e['name'] == 'error-msg' for e in received) and skill['currentCooldown'] == 0,
              (received, skill['currentCooldown']))

    p1_client.emit('commit-turn', {'paymentList': list(game['players']['p1']['resources'])})
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
            'charId': other_char['id'], 'skillId': shared_skill_id,
            'targetPlayerKey': 'p1', 'targetIndex': other_index
        })
        received = p1_client.get_received()
        errors = [e for e in received if e['name'] == 'error-msg']
        check(f"queueing {other_char['name']}'s shared skill '{shared_skill_id}' produces no error",
              errors == [], errors)

        p1_client.emit('commit-turn', {'paymentList': list(game['players']['p1']['resources'])})
        p1_client.get_received()
        check(f"the shared skill went on cooldown for {other_char['name']} specifically "
              f"(not silently the first team member with that skill id)",
              other_skill['currentCooldown'] > 0, (other_char['id'], other_skill['currentCooldown']))

        first_member_skill = next((s for s in team_members[0]['skills'] if s['id'] == shared_skill_id), None)
        if team_members[0]['id'] != other_char['id'] and first_member_skill:
            check(f"the first team member's own copy of the shared skill was untouched",
                  first_member_skill['currentCooldown'] == 0, first_member_skill['currentCooldown'])

    # --- Regression: a malformed payload used to send the raw Python error
    # (e.g. "'myPlayerKey'") to the player and log nothing. Now it's a
    # validation message; a genuine crash (simulated) gets the generic one. ---
    p2_client.get_received()
    p2_client.emit('queue-skill', {'roomId': room_id})
    errors = [e['args'][0] for e in p2_client.get_received() if e['name'] == 'error-msg']
    check("a malformed queue-skill payload gets a clear validation message",
          len(errors) == 1 and errors[0].startswith("Invalid request"), errors)

    real_queue_move = appmod.game_engine.queue_move
    def crashing_queue_move(*args, **kwargs):
        raise RuntimeError("simulated bug")
    appmod.game_engine.queue_move = crashing_queue_move
    try:
        p2_client.emit('queue-skill', {'charId': 'x', 'skillId': 'y', 'targetPlayerKey': 'p1', 'targetIndex': 0})
        errors = [e['args'][0] for e in p2_client.get_received() if e['name'] == 'error-msg']
    finally:
        appmod.game_engine.queue_move = real_queue_move
    check("an unexpected server error shows the player a generic message, not internals",
          errors == [appmod.SERVER_ERROR_MSG], errors)

    # --- The acting player always comes from the connection, never the payload ---
    p1_client.get_received()
    p1_client.emit('queue-skill', {'charId': game['players']['p2']['team'][0]['id'], 'skillId': 'x',
                                   'myPlayerKey': 'p2', 'targetPlayerKey': 'p1', 'targetIndex': 0})
    errors = [e['args'][0] for e in p1_client.get_received() if e['name'] == 'error-msg']
    check("claiming the other slot via myPlayerKey is ignored (p1 acting on p2's turn -> Not your turn)",
          errors == ["Not your turn!"], errors)
    p1_client.emit('commit-turn', {'paymentList': []})
    errors = [e['args'][0] for e in p1_client.get_received() if e['name'] == 'error-msg']
    check("commit-turn out of turn is answered, not silently ignored", errors == ["Not your turn!"], errors)

    # --- Regression: a counter-trap used to be reported as an error to the
    # attacker only, so its HP loss wasn't shown to anyone until later. ---
    # (turn auto-advanced to p2 after the commit above)
    trapped = next((c for c in game['players']['p2']['team']
                    if c['health'] > 0 and not any(s['type'] == 'stun' for s in c.get('status', []))), None)
    trap_skill = trapped and next((s for s in trapped['skills'] if not s.get('locked') and s['currentCooldown'] == 0
                                   and s.get('target_type', 'enemy') in ('enemy', 'self', 'enemy_team')), None)
    if not trap_skill:
        print("\nSKIPPED: counter-trap broadcast check needs an unstunned p2 character with a usable skill.")
    else:
        hp_before = trapped['health']
        trapped['status'].append({'type': 'marked_for_counter', 'value': 20, 'duration': 2,
                                  'tag': 'harmful', 'invisible': True})
        p1_client.get_received()
        p2_client.get_received()
        target_pid = 'p2' if trap_skill.get('target_type') == 'self' else 'p1'
        p2_client.emit('queue-skill', {
            'charId': trapped['id'], 'skillId': trap_skill['id'],
            'targetPlayerKey': target_pid, 'targetIndex': 0
        })
        got1, got2 = p1_client.get_received(), p2_client.get_received()
        check("a counter-trap is not reported as an error", not any(e['name'] == 'error-msg' for e in got2), got2)
        check("a counter-trap's damage is applied", trapped['health'] == max(0, hp_before - 20), trapped['health'])
        check("both players receive the new state and the counter message",
              all(any(e['name'] == 'update-state' for e in g) and any(e['name'] == 'message' for e in g)
                  for g in (got1, got2)), (got1, got2))

    # --- Regression: a missing paymentList used to crash resolve_turn with a raw TypeError ---
    if not game.get('winner'):
        p2_client.get_received()
        p2_client.emit('commit-turn', {})
        errors = [e['args'][0] for e in p2_client.get_received() if e['name'] == 'error-msg']
        check("commit-turn without a paymentList gets a clear validation message",
              len(errors) == 1 and 'paymentList' in errors[0], errors)

    # --- End the match the way ENG-1 used to break it: p2's whole team is
    # wiped by delayed hits detonating at the start of p1's turn. The match
    # must end immediately (no further commit needed) and persist. ---
    for c in game['players']['p2']['team']:
        if c['health'] > 0:
            c['health'] = 5
            c['status'].append({'type': 'delayed_damage', 'value': 40, 'duration': 1, 'tag': 'harmful'})
    p1_client.get_received()
    p2_client.get_received()
    p2_client.emit('commit-turn', {'paymentList': []})
    got1, got2 = p1_client.get_received(), p2_client.get_received()
    check("a team wiped by turn-start detonations ends the match immediately", game.get('winner') == 'p1',
          game.get('winner'))
    check("...and both players receive the final state with the winner and a game-over message",
          all(any(e['name'] == 'update-state' and e['args'][0].get('winner') == 'p1' for e in got)
              and any(e['name'] == 'message' for e in got) for got in (got1, got2)), (got1, got2))

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

    # --- Regression: find-match payloads weren't validated (a non-list
    # crashed the handler; 3 copies of one character were accepted). ---
    p1_client.get_received()
    p1_client.emit('find-match', 5)
    errors = [e['args'][0] for e in p1_client.get_received() if e['name'] == 'error-msg']
    check("find-match with a non-list payload gets a clear message", errors == ["You must select exactly 3 characters!"], errors)
    same = game['players']['p1']['team'][0]['id']
    p1_client.emit('find-match', [same, same, same])
    got = p1_client.get_received()
    errors = [e['args'][0] for e in got if e['name'] == 'error-msg']
    check("find-match rejects the same character picked 3 times",
          errors == ["Pick 3 different characters!"] and not any(e['name'] == 'match-status' for e in got), got)
    check("...and nobody was put in the matchmaking queue", appmod.MATCHMAKING_QUEUE == [], appmod.MATCHMAKING_QUEUE)

    # --- Regression: one account in two tabs could be matched against itself. ---
    queue_obj = appmod.MATCHMAKING_QUEUE
    client1.get_received()
    client1.emit('find-match', team_ids)
    check("(setup) account 1 is searching", len(appmod.MATCHMAKING_QUEUE) == 1, appmod.MATCHMAKING_QUEUE)
    second_tab = appmod.socketio.test_client(appmod.app, flask_test_client=flask_client1)
    second_tab.get_received()
    second_tab.emit('find-match', team_ids)
    got = second_tab.get_received()
    errors = [e['args'][0] for e in got if e['name'] == 'error-msg']
    check("the same account can't search again from a second tab",
          errors == ["This account is already searching for a match in another tab!"]
          and not any(e['name'] == 'game-start' for e in got), got)
    check("...so it is never matched against itself", len(appmod.MATCHMAKING_QUEUE) == 1, appmod.MATCHMAKING_QUEUE)
    second_tab.disconnect()
    client1.disconnect()
    check("closing the searching tab removes it from the queue (same list object, in place)",
          appmod.MATCHMAKING_QUEUE == [] and appmod.MATCHMAKING_QUEUE is queue_obj, appmod.MATCHMAKING_QUEUE)

    # An account still playing an unfinished match (e.g. in another tab) can't start a second one.
    user2_id = r2.get_json()['id']
    appmod.GAMES['fake-active'] = {'winner': None, 'players': {'p1': {'user_id': user2_id}, 'p2': {'user_id': -1}}}
    try:
        client2.get_received()
        client2.emit('find-match', team_ids)
        errors = [e['args'][0] for e in client2.get_received() if e['name'] == 'error-msg']
    finally:
        del appmod.GAMES['fake-active']
    check("an account already in an unfinished match can't search for another",
          errors == ["This account is already in a match in another tab!"], errors)
    check("...and wasn't queued", appmod.MATCHMAKING_QUEUE == [], appmod.MATCHMAKING_QUEUE)

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    raise SystemExit(1)
else:
    print("Integration smoke test passed.")
