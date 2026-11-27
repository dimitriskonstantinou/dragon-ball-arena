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
import os
import uuid

# This test creates ~20 accounts from one address (127.0.0.1); the real
# per-IP registration limit (5/hour) is exercised separately below.
os.environ.setdefault('REGISTER_LIMIT', '100000')

import app as appmod
import logging


class LogCapture(logging.Handler):
    """Keeps every log line of this whole run (Step 35 checks what was logged -- and that no secret was)."""
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        text = record.getMessage()
        if record.exc_info:
            text += '\n' + logging.Formatter().formatException(record.exc_info)
        self.lines.append(f"{record.levelname} {record.name}: {text}")


LOGS = LogCapture()
logging.getLogger().addHandler(LOGS)

# The turn timer is driven by hand below (with a shifted clock), so the real
# background ticker must not fire at random moments during the test.
appmod.TURN_TIMER_THREAD = False

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
    server_side = appmod.characters_for_user(user1)

# Regression: primed_image (e.g. Yamcha's Spirit Ball icon) used to be sent as a
# bare filename, so the browser 404'd on it (found by the Playwright test).
# Checked on the server-side team data, which still carries the effects.
urls = [u for c in server_side.values() for u in all_image_urls(c)]
not_site_relative = [u for u in urls if not u.startswith('/photos/')]
check("every image URL in match teams is a site-relative /photos/ URL, including primed skill images",
      not_site_relative == [] and any('SpiritBall' in u for u in urls) == ('yamcha_saiyan_saga' in server_side),
      not_site_relative)
missing = [u for u in sorted(set(urls)) if flask_client1.get(u).status_code != 200]
check(f"...and every one of them ({len(set(urls))}) is actually served", missing == [], missing)

# --- Step 26 regression: image URLs were built from the request's Host header, so
# behind a proxy they pointed at its internal address (broken images) and any
# client could make the server echo a host name of its choice. No health check. ---
proxied = appmod.app.test_client()   # the browser's view: logged in on the address the proxy forwards
register(proxied, f'px_{suffix}', f'px_{suffix}@test.local')
proxied.post('/api/login', json={'username': f'px_{suffix}', 'password': 'testpass123'}, base_url='http://127.0.0.1:8000')
behind_proxy = appmod.socketio.test_client(appmod.app, flask_test_client=proxied, headers={'Host': '127.0.0.1:8000'})
listed = [c for e in behind_proxy.get_received() if e['name'] == 'character-list' for c in e['args'][0]]
behind_proxy.disconnect()
check("the lobby's image URLs don't depend on the Host header a request arrived with",
      listed and all(c['image'].startswith('/photos/') and '8000' not in c['image'] for c in listed),
      [c['image'] for c in listed[:2]])
health = appmod.app.test_client().get('/healthz')
check("/healthz answers 200 {'status': 'ok'} without a login, never cached, revealing nothing else",
      health.status_code == 200 and health.get_json() == {'status': 'ok'}
      and health.headers.get('Cache-Control') == 'no-store', (health.status_code, health.get_data(as_text=True)))
real_execute = appmod.db.session.execute
def database_down(*a, **k):
    raise RuntimeError('simulated database outage')
appmod.db.session.execute = database_down
try:
    sick = appmod.app.test_client().get('/healthz')
finally:
    appmod.db.session.execute = real_execute
check("...and 503 'unavailable' when the database doesn't answer (so the host can restart/alert)",
      sick.status_code == 503 and sick.get_json() == {'status': 'unavailable'}, sick.status_code)
check("...and the app works normally again afterwards", appmod.app.test_client().get('/healthz').status_code == 200)

# --- Step 22 regression: unlimited password guessing and account creation from one IP.
# Limiters with the real defaults (5 failed logins / 5 min, 5 accounts / hour) are swapped in. ---
import time as _time
real_login_limiter, real_register_limiter = appmod.login_limiter, appmod.register_limiter
appmod.login_limiter = type(real_login_limiter)(5, 300, clock=appmod.now)
appmod.register_limiter = type(real_register_limiter)(5, 3600, clock=appmod.now)
try:
    rl = appmod.app.test_client()
    attacker, bystander = {'REMOTE_ADDR': '203.0.113.10'}, {'REMOTE_ADDR': '203.0.113.11'}
    target = f'rl_{suffix}'
    register(rl, target, f'{target}@test.local')
    codes = [rl.post('/api/login', json={'username': target, 'password': 'wrong'}, environ_base=attacker).status_code
             for _ in range(6)]
    check("5 failed logins are answered normally, the 6th is refused (429)", codes == [401] * 5 + [429], codes)
    locked = rl.post('/api/login', json={'username': target, 'password': 'testpass123'}, environ_base=attacker)
    check("...while locked out even the correct password is refused (no testing guesses)",
          locked.status_code == 429 and locked.headers.get('Retry-After', '').isdigit()
          and 'Try again in' in locked.get_json()['error'], (locked.status_code, locked.get_json()))
    other = rl.post('/api/login', json={'username': target, 'password': 'testpass123'}, environ_base=bystander)
    check("...other addresses are unaffected", other.status_code == 200, other.status_code)
    real_time = _time.time
    _time.time = lambda: real_time() + 301
    try:
        later = rl.post('/api/login', json={'username': target, 'password': 'testpass123'}, environ_base=attacker)
    finally:
        _time.time = real_time
    check("...and the address can log in again once the window has passed", later.status_code == 200, later.status_code)

    spammer = {'REMOTE_ADDR': '203.0.113.12'}
    invalid = [rl.post('/api/register', json={'username': 'x', 'email': 'bad', 'password': '1'}, environ_base=spammer).status_code
               for _ in range(3)]
    created = [rl.post('/api/register', json={'username': f'sp{i}_{suffix}', 'email': f'sp{i}_{suffix}@test.local',
                                              'password': 'spampass1'}, environ_base=spammer).status_code for i in range(6)]
    check("rejected registration forms don't count towards the limit", invalid == [400] * 3, invalid)
    check("5 new accounts per address per hour, the 6th is refused (429)", created == [201] * 5 + [429], created)
finally:
    appmod.login_limiter, appmod.register_limiter = real_login_limiter, real_register_limiter

# --- Step 25 regression: "Goku" and "goku" could both register (impersonation), any
# string was accepted as an email, and two simultaneous registrations of one name
# crashed with a 500 (unique-index error) instead of saying "taken". ---
web = appmod.app.test_client()
look_alike = register(web, f'P1_{suffix}', f'look_{suffix}@test.local')
check("a name that differs only in capitalization from an existing one is refused",
      look_alike.status_code == 409 and look_alike.get_json() == {'error': 'username already taken'},
      (look_alike.status_code, look_alike.get_json()))
any_case = appmod.app.test_client().post('/api/login', json={'username': f'P1_{suffix.upper()}', 'password': 'testpass123'})
check("login works with any capitalization and returns the name as registered",
      any_case.status_code == 200 and any_case.get_json()['username'] == f'p1_{suffix}', any_case.get_json())
for bad_name in ('goku x', 'gōku_' + suffix[:4], 'goku<b>', 'a.b.c'):
    resp = register(web, bad_name, f'n{uuid.uuid4().hex[:6]}@test.local')
    check(f"username {bad_name!a} (not letters/digits/_/-) is refused",
          resp.status_code == 400 and 'letters, digits' in resp.get_json()['error'], resp.get_json())
for bad_email in ('not-an-email', 'a@b', '@x.io', 'a b@x.io', 'a@x.', 'x' * 251 + '@x.io'):
    resp = register(web, f'm{uuid.uuid4().hex[:8]}', bad_email)
    check(f"email {bad_email[:20]!r} is refused", resp.status_code == 400
          and resp.get_json() == {'error': 'please enter a valid email address'}, resp.get_json())
ok_email = register(appmod.app.test_client(), f'Mail-{suffix}', f'First.Last+{suffix}@Mail.Example.org')
check("a normal email (dots, plus, capitals) and a name with - and capitals are accepted",
      ok_email.status_code == 201 and ok_email.get_json()['email'] == f'first.last+{suffix}@mail.example.org',
      ok_email.get_json())

import threading as _threading
real_hash = appmod.generate_password_hash
appmod.generate_password_hash = lambda *a, **k: (_time.sleep(0.1), real_hash(*a, **k))[1]
race_results = []
try:
    def race(name, email):
        resp = register(appmod.app.test_client(), name, email)
        race_results.append((resp.status_code, resp.get_json()))

    def simultaneously(*args_pairs):
        threads = [_threading.Thread(target=race, args=args) for args in args_pairs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    simultaneously((f'Race_{suffix}', f'r1_{suffix}@test.local'), (f'race_{suffix}', f'r2_{suffix}@test.local'))
    simultaneously((f'e1_{suffix}', f'same_{suffix}@test.local'), (f'e2_{suffix}', f'same_{suffix}@test.local'))
finally:
    appmod.generate_password_hash = real_hash
check("two simultaneous registrations of one name (different capitalization): one succeeds, the other gets "
      "'username already taken' (not a 500)",
      sorted(code for code, _ in race_results[:2]) == [201, 409]
      and {'error': 'username already taken'} in [body for _, body in race_results[:2]], race_results[:2])
check("...and the same for two simultaneous registrations of one email",
      sorted(code for code, _ in race_results[2:]) == [201, 409]
      and {'error': 'email already registered'} in [body for _, body in race_results[2:]], race_results[2:])
with appmod.app.app_context():
    stored = appmod.User.query.filter(appmod.User.username_key == f'race_{suffix}').count()
check("...leaving exactly one account with that name", stored == 1, stored)

# --- Step 44 regression (BE-14): signing up and logging in kept a database connection checked out during the
# deliberately slow password hashing; 32 at once on Render's free size ran the pool dry (500 after 30 s). ---
held_while_hashing = []
real_check = appmod.check_password_hash


def watching(real):
    def hash_while_watched(*args, **kwargs):
        held_while_hashing.append(appmod.db.session().in_transaction())   # a transaction = a checked-out connection
        return real(*args, **kwargs)
    return hash_while_watched


appmod.generate_password_hash, appmod.check_password_hash = watching(real_hash), watching(real_check)
try:
    hold_name = f'hold_{suffix}'
    held = [register(appmod.app.test_client(), hold_name, f'{hold_name}@test.local').status_code]
    for password in ('testpass123', 'wrong-password'):
        held.append(appmod.app.test_client().post('/api/login', json={'username': hold_name, 'password': password},
                                                   environ_base={'REMOTE_ADDR': '198.51.100.44'}).status_code)
finally:
    appmod.generate_password_hash, appmod.check_password_hash = real_hash, real_check
check("signing up and logging in hold no database connection while the password is hashed",
      held == [201, 200, 401] and held_while_hashing == [False, False, False], (held, held_while_hashing))

# --- Step 24 regression: a login cookie never expired and couldn't be revoked -- a
# copied ("stolen") cookie kept working after its owner logged out. ---
owner, thief = appmod.app.test_client(), appmod.app.test_client()
account = f'sess_{suffix}'
reg = register(owner, account, f'{account}@test.local')
set_cookie = reg.headers.get('Set-Cookie', '')
thief.set_cookie('session', set_cookie.split(';', 1)[0].split('=', 1)[1])
check("(setup) a copied login cookie works while the owner is logged in", thief.get('/api/me').status_code == 200)
check("the login cookie has an expiry (Expires=...)", 'Expires=' in set_cookie, set_cookie)
other_tab = appmod.socketio.test_client(appmod.app, flask_test_client=owner)
check("(setup) the owner has an open game connection", other_tab.is_connected())
owner.post('/api/logout')
check("after the owner logs out, the copied cookie no longer works", thief.get('/api/me').status_code == 401)
check("...and the account's open game connections are closed", not other_tab.is_connected())
check("...but logging in again works normally",
      owner.post('/api/login', json={'username': account, 'password': 'testpass123'}).status_code == 200
      and owner.get('/api/me').status_code == 200)

days = appmod.settings.session_days
real_time = _time.time
try:
    _time.time = lambda: real_time() + (days - 1) * 86400
    still = owner.get('/api/me').status_code
    _time.time = lambda: real_time() + (days + 1) * 86400
    fresh = appmod.app.test_client()
    fresh.post('/api/login', json={'username': account, 'password': 'testpass123'})
    _time.time = lambda: real_time() + (2 * days + 2) * 86400
    stale = fresh.get('/api/me').status_code
finally:
    _time.time = real_time
check(f"a login is still valid {days - 1} days later", still == 200, still)
check(f"...and expires after {days} days without a visit (the server checks the signed timestamp)",
      stale == 401, stale)

legacy = appmod.app.test_client()
with legacy.session_transaction() as sess:   # a cookie made before Step 24: user_id but no session version
    sess['user_id'] = r1.get_json()['id']
check("an old-format cookie without a session version is not accepted", legacy.get('/api/me').status_code == 401)
other_tab.disconnect() if other_tab.is_connected() else None

# --- Step 21 regression: the page loaded socket.io from a third-party CDN (the game
# couldn't load while it was slow/down; foreign code with full page access). ---
import hashlib
import re
from importlib.metadata import version as package_version

VENDOR_CLIENT = 'vendor/socket.io-4.5.4.min.js'
VENDOR_SHA256 = '18a36a927dac54650b18b903f8f8778219e02e13946e581d9b3e1e4995f7435b'  # npm socket.io-client 4.5.4
page_client = appmod.app.test_client()
index_html = page_client.get('/').get_data(as_text=True)
external_scripts = re.findall(r'<script[^>]+src="(https?:)?//', index_html)
check("the game page loads no scripts from other servers", external_scripts == [], external_scripts)
served = page_client.get('/' + VENDOR_CLIENT)
check("the socket.io client is served by our own server as JavaScript",
      served.status_code == 200 and 'javascript' in served.content_type and f'src="{VENDOR_CLIENT}"' in index_html,
      (served.status_code, served.content_type))
check("...and is byte-for-byte the verified npm build (pinned sha256)",
      hashlib.sha256(served.get_data()).hexdigest() == VENDOR_SHA256)
server_major = int(package_version('python-socketio').split('.')[0])
client_major = int(re.search(r'socket\.io-(\d+)\.', VENDOR_CLIENT).group(1))
check("the client version is compatible with the server library (JS client 4.x <-> python-socketio 5.x)",
      (client_major, server_major) == (4, 5), (client_major, server_major))

# --- Step 20 regression: any website could open a logged-in game connection
# (cors_allowed_origins="*" + cookie auth), and the login cookie had no SameSite. ---
web = appmod.app.test_client()
def handshake(origin):
    headers = {'Origin': origin} if origin else {}
    return web.get('/socket.io/?EIO=4&transport=polling', headers=headers).status_code
check("another website's page can't open a game connection", handshake('https://evil.example') == 400)
check("...nor a look-alike of this site", handshake('http://localhost.evil.example') == 400)
check("the game's own page still can (same origin)", handshake('http://localhost') == 200)
check("a refused website is logged as a warning, not as an error", any(
    l.startswith("WARNING engineio.server: Rejected a game connection: 'https://evil.example") for l in LOGS.lines)
    and not any(l.startswith('ERROR engineio') for l in LOGS.lines), [l for l in LOGS.lines if 'engineio' in l])
web.get('/socket.io/?EIO=4&transport=polling&sid=AbCdEfGhIjKlMnOpQrSt')
check("an unknown connection id is logged shortened, as a warning", any(
    l.startswith('WARNING engineio.server: Rejected a game connection') and 'AbCdEf' in l for l in LOGS.lines)
    and not any('AbCdEfGhIjKlMnOpQrSt' in l for l in LOGS.lines), [l for l in LOGS.lines if 'engineio' in l])
login_cookie = '; '.join(r1.headers.getlist('Set-Cookie'))
check("the login cookie is HttpOnly and SameSite=Lax (other sites' requests don't carry it)",
      'HttpOnly' in login_cookie and 'SameSite=Lax' in login_cookie, login_cookie)
check("...and not Secure in development (local http://localhost logins keep working)",
      'Secure' not in login_cookie, login_cookie)

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
        offered = appmod.characters_for_user(user1)
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
          list(appmod.characters_for_user(user1)) == list(catalog))

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
    check("character image URL in the match state is site-relative (works under any domain / behind a proxy)",
          any_char['image'].startswith('/photos/characters/'), any_char['image'])

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

    # --- Step 28 regression (ENG-4): an invulnerable ("Untargetable") enemy could be
    # targeted, wasting the attacker's Ki and cooldown. ---
    if skill.get('target_type', 'enemy') == 'enemy' and not appmod.game_engine.skill_ignores_invulnerability(skill):
        guarded = game['players']['p2']['team'][0]
        guarded['status'].append({'type': 'invulnerable', 'duration': 2, 'tag': 'buff'})
        p1_client.get_received()
        p1_client.emit('queue-skill', {'charId': actor['id'], 'skillId': skill['id'],
                                       'targetPlayerKey': 'p2', 'targetIndex': 0})
        refusal = [e['args'][0] for e in p1_client.get_received() if e['name'] == 'error-msg']
        check("targeting an invulnerable enemy over Socket.IO is refused with a readable message",
              refusal == [f"{guarded['name']} is invulnerable and can't be targeted by {skill['name']}!"], refusal)
        check("...and nothing is queued", game['pending_moves'] == [], game['pending_moves'])
        guarded['status'] = [s for s in guarded['status'] if s['type'] != 'invulnerable']
    else:
        check("(setup) the first skill is a plain single-target attack", False, skill.get('target_type'))

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
    # Step 32 (ENG-7): every match has its own random stream; its seed stays on the server.
    check("the server gave this match its own random seed",
          isinstance(game.get('rng_seed'), int) and game.get('rng_draws', 0) > 0, (game.get('rng_seed'), game.get('rng_draws')))
    check("...and never sends the seed or draw counter to either player",
          all(u and 'rng_seed' not in u and 'rng_draws' not in u for u in (p1_update, p2_update)))
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

    # --- Step 29 regression (ENG-2, user 2026-11-21: no draws): when both last characters
    # were poisoned lethally, the engine named p2 the winner (it looked at p1's team first);
    # Step 27 made it a draw. Now the team wiped out FIRST loses -- poisons tick in the
    # order they were cast -- and the result is saved as a normal win/loss. ---
    ko_http = [appmod.app.test_client(), appmod.app.test_client()]
    for i, http in enumerate(ko_http, 1):
        register(http, f'ko{i}_{suffix}', f'ko{i}_{suffix}@test.local')
    k1, k2 = (appmod.socketio.test_client(appmod.app, flask_test_client=h) for h in ko_http)
    k1.emit('find-match', team_ids)
    k2.emit('find-match', team_ids)
    ko_start = next(e['args'][0] for e in k1.get_received() if e['name'] == 'game-start')
    ko_room = ko_start['roomId']
    kg = appmod.GAMES[ko_room]
    for side in ('p2', 'p1'):     # cast order: the poison on p2's last fighter first -> p2 falls first
        team = kg['players'][side]['team']
        for ch in team[1:]:
            ch['health'] = 0
        team[0]['health'] = 10
        team[0]['status'] = []
        appmod.game_engine.add_status(team[0], {'type': 'dot', 'value': 50, 'duration': 4, 'tag': 'harmful'})
    k2.get_received()
    (k1 if kg['turn'] == ko_start['role'] else k2).emit('commit-turn', {'paymentList': []})
    seen = [k1.get_received(), k2.get_received()]
    check("both last fighters poisoned: the one poisoned first falls first, so p1 wins (both players see it)",
          all(any(e['name'] == 'update-state' and e['args'][0].get('winner') == 'p1' for e in got) for got in seen),
          [[e['args'][0].get('winner') for e in got if e['name'] == 'update-state'] for got in seen])
    check("...p1's fighter is still standing (p1's own poison never ticked)",
          next(e['args'][0] for e in reversed(seen[0]) if e['name'] == 'update-state')['players']['p1']['team'][0]
          ['health'] == 10)
    check("...with the normal game-over message",
          all(any(e['name'] == 'message' and (e['args'] if isinstance(e['args'], str) else e['args'][0])
                  == "GAME OVER! P1 WINS!" for e in got) for got in seen),
          [[e['args'] for e in got if e['name'] == 'message'] for got in seen])
    check("...and no KO/cast ordering numbers reach the clients",
          not any('ko_seq' in str(e['args']) or 'cast_seq' in str(e['args']) for got in seen for e in got))
    ko_uids = [kg['players'][s]['user_id'] for s in ('p1', 'p2')]
    with appmod.app.app_context():
        rows = [appmod.db.session.get(appmod.UserStats, uid) for uid in ko_uids]
        check("stats: p1 gets a win, p2 a loss (no draws)",
              [(s.total_matches, s.total_wins, s.total_losses) for s in rows] == [(1, 1, 0), (1, 0, 1)],
              [(s.total_matches, s.total_wins, s.total_losses) for s in rows])
        ko_row = appmod.Match.query.filter(appmod.Match.player1_id.in_(ko_uids)).one()
        check("the match is saved with p1 as the winner", ko_row.winner_id == ko_uids[0], ko_row.winner_id)
    me = ko_http[0].get('/api/me').get_json()
    check("the player's own stats have no draw field", 'total_draws' not in me['stats'], me['stats'])
    k1.disconnect(); k2.disconnect()

    # --- Step 13 regression: finished matches used to stay in memory forever
    # (GAMES, ENDED_ROOMS and the Socket.IO room; ~30 KB each). ---
    socket_rooms = appmod.socketio.server.manager.rooms.get('/', {})
    check("a finished match is removed from memory", room_id not in appmod.GAMES, list(appmod.GAMES))
    check("...and its Socket.IO room is closed", room_id not in socket_rooms)
    check("...and neither player is still mapped to it",
          not any(r == room_id for r in appmod.SID_ROOM_MAP.values()))
    p1_client.get_received()
    p1_client.emit('commit-turn', {'paymentList': []})
    errors = [e['args'][0] for e in p1_client.get_received() if e['name'] == 'error-msg']
    check("a late action after the match ended gets a clear answer", errors == ["You are not in a match."], errors)

    def play_quick_match():
        """Both players queue again; the match ends at once (p2's team wiped)."""
        p1_client.get_received(); p2_client.get_received()
        p1_client.emit('find-match', team_ids)
        p2_client.emit('find-match', team_ids)
        start = next((e['args'][0] for e in p1_client.get_received() if e['name'] == 'game-start'), None)
        if not start:
            return None
        g = appmod.GAMES[start['roomId']]
        for ch in g['players']['p2']['team']:
            ch['health'] = 0
        (p1_client if start['role'] == 'p1' else p2_client).emit('commit-turn', {'paymentList': []})
        return start['roomId'] if g.get('winner') else None

    finished = [play_quick_match() for _ in range(20)]
    check("the same two players can play again and again (20 more matches)", all(finished), finished)
    check("...and after all of them no match is left in memory",
          appmod.GAMES == {} and not any(r in appmod.socketio.server.manager.rooms.get('/', {}) for r in finished),
          list(appmod.GAMES))
    check("...and no per-match locks are left behind either", appmod.ROOM_LOCKS == {}, list(appmod.ROOM_LOCKS))

    # --- Step 14 regression: if saving the result failed, end_game raised before
    # the final broadcast, so neither player saw the match end. Simulated with a
    # real failing COMMIT (not a patched function), so the rollback is tested too.
    import logging
    from sqlalchemy import event

    def total_matches():
        with appmod.app.app_context():
            return tuple(appmod.db.session.get(appmod.UserStats, uid).total_matches for uid in (winner_uid, loser_uid))

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    def failing_commit(session):
        raise RuntimeError('simulated database outage')

    capture = Capture()
    appmod.log.addHandler(capture)
    before = total_matches()
    event.listen(appmod.db.session, 'before_commit', failing_commit)
    try:
        p1_client.get_received(); p2_client.get_received()
        p1_client.emit('find-match', team_ids)
        p2_client.emit('find-match', team_ids)
        start = next(e['args'][0] for e in p1_client.get_received() if e['name'] == 'game-start')
        p2_client.get_received()
        for ch in appmod.GAMES[start['roomId']]['players']['p2']['team']:
            ch['health'] = 0
        p1_client.emit('commit-turn', {'paymentList': []})
        got1, got2 = p1_client.get_received(), p2_client.get_received()
    finally:
        event.remove(appmod.db.session, 'before_commit', failing_commit)
        appmod.log.removeHandler(capture)

    check("when saving the result fails, both players still get the final state and the game-over message",
          all(any(e['name'] == 'update-state' and e['args'][0].get('winner') for e in got)
              and any(e['name'] == 'message' for e in got) for got in (got1, got2)), (got1, got2))
    check("...the player who made the move doesn't get a server error",
          not any(e['name'] == 'error-msg' for e in got1), got1)
    check("...the failure is logged with what's needed to restore the result",
          any('Could not save match result' in m and start['roomId'] in m for m in capture.messages), capture.messages)
    check("...nothing is half-saved (no stats changed)", total_matches() == before, (before, total_matches()))
    check("...and the match is still removed from memory", start['roomId'] not in appmod.GAMES)
    check("after the failure, the next match saves normally (the session was rolled back)",
          play_quick_match() and total_matches() == tuple(n + 1 for n in before), (before, total_matches()))

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

    # --- Step 15 regression: the real server runs every event in its own thread
    # (async_handlers), while this test client handles events synchronously. So
    # these checks fire events from parallel threads, widening the race window by
    # slowing one step down (50 ms) like a busy server would. ---
    import threading
    import time

    def at_once(*calls):
        threads = [threading.Thread(target=c) for c in calls]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def slowed(name, target=appmod):
        real = getattr(target, name)

        def slow(*args, **kwargs):
            time.sleep(0.05)
            return real(*args, **kwargs)
        setattr(target, name, slow)
        return lambda: setattr(target, name, real)

    def new_player(tag):
        http = appmod.app.test_client()
        register(http, f'{tag}_{suffix}', f'{tag}_{suffix}@test.local')
        client = appmod.socketio.test_client(appmod.app, flask_test_client=http)
        client.get_received()
        return http, client

    _, racer1 = new_player('race1')
    _, racer2 = new_player('race2')
    racer1.emit('find-match', team_ids)
    racer2.emit('find-match', team_ids)
    start = next(e['args'][0] for e in racer1.get_received() if e['name'] == 'game-start')
    g = appmod.GAMES[start['roomId']]
    mover = racer1 if start['role'] == 'p1' else racer2
    turns_before = g['turn_count']
    mover.get_received()
    restore = slowed('resolve_turn', appmod.game_engine)
    try:
        at_once(lambda: mover.emit('commit-turn', {'paymentList': []}),
                lambda: mover.emit('commit-turn', {'paymentList': []}))
    finally:
        restore()
    errors = [e['args'][0] for e in mover.get_received() if e['name'] == 'error-msg']
    check("a double commit (two threads at once) resolves only one turn",
          g['turn_count'] == turns_before + 1 and g['turn'] != start['role'], (g['turn_count'] - turns_before, g['turn']))
    check("...and the second commit is told it's not your turn", errors == ["Not your turn!"], errors)
    # Finish that match properly (since Step 17 a disconnect no longer forfeits at once).
    racers = {start['role']: racer1, ('p2' if start['role'] == 'p1' else 'p1'): racer2}
    for ch in g['players']['p1' if g['turn'] == 'p2' else 'p2']['team']:
        ch['health'] = 0
    racers[g['turn']].emit('commit-turn', {'paymentList': []})
    check("(cleanup) the race match ended", start['roomId'] not in appmod.GAMES)
    racer1.disconnect()
    racer2.disconnect()

    http_tabs, tab1 = new_player('tabs')
    tab2 = appmod.socketio.test_client(appmod.app, flask_test_client=http_tabs)
    tab2.get_received()
    restore = slowed('characters_for_user')
    try:
        at_once(lambda: tab1.emit('find-match', team_ids), lambda: tab2.emit('find-match', team_ids))
    finally:
        restore()
    got = tab1.get_received() + tab2.get_received()
    check("two tabs of one account searching at the same instant are never matched together",
          not any(e['name'] == 'game-start' for e in got)
          and [e['args'][0] for e in got if e['name'] == 'error-msg']
          == ["This account is already searching for a match in another tab!"], got)
    tab1.disconnect()
    tab2.disconnect()
    check("(cleanup) queue empty after the tabs left", appmod.MATCHMAKING_QUEUE == [], appmod.MATCHMAKING_QUEUE)

    crowd = [new_player(f'crowd{i}')[1] for i in range(4)]
    client_by_sid = {appmod.socketio.server.manager.sid_from_eio_sid(c.eio_sid, '/'): c for c in crowd}
    stray_errors, started = [], 0
    for _ in range(10):
        at_once(*[(lambda c=c: c.emit('find-match', team_ids)) for c in crowd])
        received = [c.get_received() for c in crowd]
        stray_errors += [e for r in received for e in r if e['name'] == 'error-msg']
        started += sum(1 for r in received for e in r if e['name'] == 'game-start')
        for g in list(appmod.GAMES.values()):  # end the matches so everyone can search again
            for ch in g['players']['p2']['team']:
                ch['health'] = 0
            client_by_sid[g['players']['p1']['id']].emit('commit-turn', {'paymentList': []})
    check("4 players searching at the same instant, 10 rounds: every one matched, no errors or crashes",
          stray_errors == [] and started == 4 * 10 and appmod.MATCHMAKING_QUEUE == [] and appmod.GAMES == {},
          (stray_errors[:3], started, appmod.MATCHMAKING_QUEUE, list(appmod.GAMES)))
    for c in crowd:
        c.disconnect()

    # --- Step 38 regression (BE-12): a connection that dies while it is being paired. Its "find-match"
    # (own thread) can run after its disconnect was handled; the match was then created halfway, without
    # a turn or a deadline, and the opponent was "already in a match" forever. ---
    def sid_of(client):
        return appmod.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')

    def search_and_vanish(client):
        # The connection drops while the server is still handling this player's search.
        real = appmod.characters_for_user

        def drops(*args, **kwargs):
            appmod.characters_for_user = real
            client.disconnect()
            return real(*args, **kwargs)
        appmod.characters_for_user = drops
        try:
            client.emit('find-match', team_ids)
        finally:
            appmod.characters_for_user = real

    def names(client):
        return [e['name'] for e in client.get_received()]

    def leftovers():
        return (list(appmod.GAMES), list(appmod.ROOM_LOCKS), dict(appmod.SID_ROOM_MAP),
                [p['username'] for p in appmod.MATCHMAKING_QUEUE])

    NOTHING = ([], [], {}, [])

    def surrender_match(first, second):
        first.emit('surrender', {})
        first.get_received()
        second.get_received()
        return leftovers() == NOTHING

    check("(setup) no match or search is left over", leftovers() == NOTHING, leftovers())
    errors_before = sum(l.startswith('ERROR') for l in LOGS.lines)
    _, ghost = new_player('ghost1')
    search_and_vanish(ghost)
    check("a search handled after its player disconnected joins no queue", leftovers() == NOTHING, leftovers())

    _, ghost = new_player('ghost2')
    _, alive1 = new_player('alive1')
    _, alive2 = new_player('alive2')
    alive1.emit('find-match', team_ids)
    alive1.get_received()
    search_and_vanish(ghost)
    check("...and isn't paired with a waiting player, who keeps waiting",
          'game-start' not in names(alive1) and appmod.GAMES == {}
          and [p['id'] for p in appmod.MATCHMAKING_QUEUE] == [sid_of(alive1)], leftovers())
    alive2.emit('find-match', team_ids)
    check("...and that waiting player gets the next real opponent",
          'game-start' in names(alive1) and 'game-start' in names(alive2) and len(appmod.GAMES) == 1, leftovers())
    check("(cleanup) that match ended", surrender_match(alive1, alive2), leftovers())

    # Queued, then the connection starts closing; its disconnect handler hasn't run yet when the next
    # player searches (the library marks the connection first, then calls the handler).
    _, dying = new_player('dying')
    dying.emit('find-match', team_ids)
    dying_sid = sid_of(dying)
    appmod.socketio.server.manager.pre_disconnect(dying_sid, '/')
    alive1.emit('find-match', team_ids)
    got = names(alive1)
    check("a queued player whose connection is closing is skipped, not matched",
          'game-start' not in got and 'error-msg' not in got and appmod.GAMES == {}
          and [p['id'] for p in appmod.MATCHMAKING_QUEUE] == [sid_of(alive1)], (got, leftovers()))
    appmod.socketio.server.manager.disconnect(dying_sid, '/')
    alive2.emit('find-match', team_ids)
    check("...and the player behind it is matched with the next one",
          'game-start' in names(alive1) and 'game-start' in names(alive2), leftovers())
    check("(cleanup) that match ended too", surrender_match(alive1, alive2), leftovers())
    check("none of this is logged as an error", sum(l.startswith('ERROR') for l in LOGS.lines) == errors_before)

    # Any other failure while a match is being created must leave nothing behind either.
    for failing in ('join_room', 'broadcast_state'):
        alive1.emit('find-match', team_ids)
        alive1.get_received()
        real = getattr(appmod, failing)
        calls = []

        def breaks(*args, **kwargs):
            calls.append(1)
            if failing == 'broadcast_state' or len(calls) == 2:   # join_room: the SECOND player's
                raise RuntimeError("simulated failure while creating a match")
            return real(*args, **kwargs)
        setattr(appmod, failing, breaks)
        try:
            alive2.emit('find-match', team_ids)
        finally:
            setattr(appmod, failing, real)
        got1, got2 = alive1.get_received(), alive2.get_received()
        check(f"a crash while creating a match ({failing}) leaves no match, seat or lock behind",
              leftovers() == NOTHING, leftovers())
        check(f"...both players are told ({failing})", all(
            any(e['name'] == 'error-msg' for e in got) and got[-1]['name'] in ('match-status', 'error-msg')
            and any(e['name'] == 'match-status' and e['args'][0] == appmod.MATCH_FAILED_MSG for e in got)
            for got in (got1, got2)), (got1, got2))
        alive1.emit('find-match', team_ids)
        alive2.emit('find-match', team_ids)
        check(f"...and both can search and play again ({failing})",
              'game-start' in names(alive1) and 'game-start' in names(alive2), leftovers())
        check(f"(cleanup) the match after the crash ended ({failing})", surrender_match(alive1, alive2), leftovers())
    alive1.disconnect()
    alive2.disconnect()

    # --- Step 16 regression: no turn timer -- an idle player could hold a match
    # forever, and the opponent's only way out (leaving) recorded THEIR loss. ---
    from contextlib import contextmanager

    @contextmanager
    def clock_ahead(seconds):
        real = time.time
        time.time = lambda: real() + seconds
        try:
            yield
        finally:
            time.time = real

    def tick():
        with appmod.app.app_context():
            appmod.check_turn_timers()

    def text(event):
        # The test client records args of events emitted outside a request (the
        # timer) as a bare string instead of a list; real clients get the string.
        return event['args'] if isinstance(event['args'], str) else event['args'][0]

    _, idle1 = new_player('idle1')
    _, idle2 = new_player('idle2')
    idle1.emit('find-match', team_ids)
    idle2.emit('find-match', team_ids)
    got = idle1.get_received()
    start = next(e['args'][0] for e in got if e['name'] == 'game-start')
    first_state = next(e['args'][0] for e in got if e['name'] == 'update-state')
    room = start['roomId']
    g = appmod.GAMES[room]
    slow_side = start['role']                    # this player never acts
    other_side = 'p2' if slow_side == 'p1' else 'p1'
    clients = {start['role']: idle1, other_side: idle2}
    check("each turn starts with a countdown sent to the players (and no raw server clock)",
          first_state.get('turn_seconds_left') == appmod.TURN_SECONDS and 'turn_deadline' not in first_state,
          {k: first_state.get(k) for k in ('turn_seconds_left', 'turn_deadline')})

    with clock_ahead(appmod.TURN_SECONDS - 5):
        tick()
    check("nothing happens before the deadline", g['turn'] == slow_side and g['turn_count'] == 1, g['turn'])

    idle1.get_received(); idle2.get_received()
    with clock_ahead(appmod.TURN_SECONDS + 1):
        tick()
    got_slow, got_other = clients[slow_side].get_received(), clients[other_side].get_received()
    check("after the deadline the idle player's turn passes to the opponent",
          g['turn'] == other_side and g['players'][slow_side]['timeouts'] == 1, (g['turn'], g['players'][slow_side]))
    check("...both players are told why and get the new state",
          all(any(e['name'] == 'message' and 'ran out of time' in text(e) for e in got)
              and any(e['name'] == 'update-state' for e in got) for got in (got_slow, got_other)))

    # The opponent commits (resetting nothing for the idle player); the idle one keeps timing out.
    clients[other_side].emit('commit-turn', {'paymentList': []})
    check("a real commit resets the committing player's streak",
          g['players'][other_side].get('timeouts', 0) == 0 and g['turn'] == slow_side)

    # Race: the timer fires at the same moment as a (slow) commit -- only one may count.
    restore = slowed('resolve_turn', appmod.game_engine)
    count_before = g['turn_count']
    try:
        with clock_ahead(appmod.TURN_SECONDS + 1):
            at_once(lambda: clients[slow_side].emit('commit-turn', {'paymentList': []}), tick)
    finally:
        restore()
    check("a commit and a timeout at the same moment advance the match by exactly one turn",
          g['turn_count'] == count_before + 1, g['turn_count'] - count_before)

    # Back to the idle player's turn, then let them time out until they forfeit.
    if g['turn'] != slow_side:
        clients[other_side].emit('commit-turn', {'paymentList': []})
    g['players'][slow_side]['timeouts'] = 0
    with appmod.app.app_context():
        stats = {uid: appmod.db.session.get(appmod.UserStats, uid).total_losses
                 for uid in (g['players'][slow_side]['user_id'], g['players'][other_side]['user_id'])}
    slow_uid, other_uid = g['players'][slow_side]['user_id'], g['players'][other_side]['user_id']
    idle1.get_received(); idle2.get_received()
    for _ in range(appmod.game_engine.TIMEOUTS_TO_FORFEIT):
        with clock_ahead(appmod.TURN_SECONDS + 1):
            tick()                                    # idle player times out
        if room in appmod.GAMES and g['turn'] == other_side:
            clients[other_side].emit('commit-turn', {'paymentList': []})   # opponent plays on
    got_other = clients[other_side].get_received()
    check(f"{appmod.game_engine.TIMEOUTS_TO_FORFEIT} timeouts in a row forfeit the match to the opponent",
          g.get('winner') == other_side and room not in appmod.GAMES, (g.get('winner'), room in appmod.GAMES))
    check("...and the opponent is told it was a forfeit",
          any(e['name'] == 'message' and 'FORFEITS' in text(e) for e in got_other), got_other)
    with appmod.app.app_context():
        check("...and the loss is recorded for the idle player only",
              appmod.db.session.get(appmod.UserStats, slow_uid).total_losses == stats[slow_uid] + 1
              and appmod.db.session.get(appmod.UserStats, other_uid).total_losses == stats[other_uid])
    idle1.disconnect()
    idle2.disconnect()

    # --- Step 17 regression: a disconnect mid-match (page reload, closed lid,
    # Wi-Fi -> mobile data) used to forfeit instantly. Now the same account has
    # RECONNECT_SECONDS to come back before it counts as a forfeit. ---
    def check_disconnects():
        with appmod.app.app_context():
            appmod.check_disconnect_timers()

    def match_of(c1, c2):
        c1.emit('find-match', team_ids)
        c2.emit('find-match', team_ids)
        start = next(e['args'][0] for e in c1.get_received() if e['name'] == 'game-start')
        c2.get_received()
        return start['roomId'], start['role'], ('p2' if start['role'] == 'p1' else 'p1')

    http_back, back1 = new_player('back1')
    _, back2 = new_player('back2')
    room, my_role, their_role = match_of(back1, back2)
    g = appmod.GAMES[room]
    my_uid = g['players'][my_role]['user_id']

    back1.disconnect()                                   # e.g. the page is reloaded
    got2 = back2.get_received()
    check("a disconnect mid-match doesn't end it", room in appmod.GAMES and not g.get('winner'))
    check("...the opponent is told how long the player has to come back",
          any(e['name'] == 'message' and f'waiting up to {appmod.RECONNECT_SECONDS}s' in text(e) for e in got2), got2)
    states = [e['args'][0] for e in got2 if e['name'] == 'update-state']
    check("...and sees them as disconnected (without the server's timestamp)",
          states and states[-1]['players'][my_role]['connected'] is False
          and all('disconnected_at' not in st['players'][r] for st in states for r in ('p1', 'p2')))

    with clock_ahead(appmod.RECONNECT_SECONDS - 5):
        check_disconnects()
    check("nothing happens before the grace period ends", room in appmod.GAMES and not g.get('winner'))

    back1 = appmod.socketio.test_client(appmod.app, flask_test_client=http_back)   # same account comes back
    got1, got2 = back1.get_received(), back2.get_received()
    check("coming back in time puts the player back into the same match, same role",
          any(e['name'] == 'game-start' and e['args'][0] == {'roomId': room, 'role': my_role} for e in got1), got1)
    states = [e['args'][0] for e in got1 if e['name'] == 'update-state']
    check("...with the current state, shown as connected again",
          states and states[-1]['players'][my_role]['connected'] is True and len(states[-1]['players'][my_role]['team']) == 3)
    check("...and the opponent is told", any(e['name'] == 'message' and 'RECONNECTED' in text(e) for e in got2), got2)
    if g['turn'] != my_role:
        back2.emit('commit-turn', {'paymentList': []})
        back1.get_received()
    back1.emit('commit-turn', {'paymentList': []})
    errors = [e for e in back1.get_received() if e['name'] == 'error-msg']
    check("...and can play on (their commit is accepted)", errors == [] and g['turn'] == their_role, (errors, g['turn']))
    check("...and no disconnect bookkeeping is left for them", my_uid not in appmod.DISCONNECTED_USERS)

    with appmod.app.app_context():
        losses_before = appmod.db.session.get(appmod.UserStats, my_uid).total_losses
    back1.disconnect()                                   # leaves again, and this time stays away
    back2.get_received()
    with clock_ahead(appmod.RECONNECT_SECONDS + 1):
        check_disconnects()
    got2 = back2.get_received()
    check("staying away past the grace period forfeits the match to the opponent",
          g.get('winner') == their_role and room not in appmod.GAMES, (g.get('winner'), room in appmod.GAMES))
    check("...and the opponent is told why",
          any(e['name'] == 'message' and "DIDN'T COME BACK IN TIME" in text(e) for e in got2), got2)
    with appmod.app.app_context():
        check("...and the loss is recorded for the player who left",
              appmod.db.session.get(appmod.UserStats, my_uid).total_losses == losses_before + 1)
    check("...and no disconnect bookkeeping is left behind", appmod.DISCONNECTED_USERS == {}, appmod.DISCONNECTED_USERS)
    back2.disconnect()

    # A second tab of a player who is still connected must not take over the seat.
    http_seat, seat1 = new_player('seat1')
    _, seat2 = new_player('seat2')
    room, my_role, their_role = match_of(seat1, seat2)
    g = appmod.GAMES[room]
    sid_before = g['players'][my_role]['id']
    intruder = appmod.socketio.test_client(appmod.app, flask_test_client=http_seat)
    check("a second tab while still connected doesn't take over the match",
          not any(e['name'] == 'game-start' for e in intruder.get_received()) and g['players'][my_role]['id'] == sid_before)
    for ch in g['players'][their_role]['team']:
        ch['health'] = 0
    {my_role: seat1, their_role: seat2}[g['turn']].emit('commit-turn', {'paymentList': []})
    if room in appmod.GAMES:   # p2 had the turn: let it pass once more
        {my_role: seat1, their_role: seat2}[g['turn']].emit('commit-turn', {'paymentList': []})
    check("(cleanup) that match ended", room not in appmod.GAMES)
    for c in (intruder, seat1, seat2):
        c.disconnect()

    # --- Step 39 regression (BE-13): the connection coming back dies while it is being put back into its
    # match. The seat was then marked as back but belonged to nobody: no forfeit, and no way back in. ---
    def return_and_die(http, how):
        # Connects, and the connection dies while the server handles that connect. Returns its sid.
        real, sids = appmod.characters_for_user, []
        manager = appmod.socketio.server.manager

        def dies(*args, **kwargs):
            appmod.characters_for_user = real
            sid = appmod.request.sid
            sids.append(sid)
            if how == 'closed':                         # completely gone (e.g. logout in another tab)
                appmod.socketio.server.disconnect(sid)
            else:                                       # closing: our disconnect handler has run, the
                manager.pre_disconnect(sid, '/')        # library hasn't forgotten the connection yet
                appmod.socketio.server._trigger_event('disconnect', '/', sid, 'test')
            return real(*args, **kwargs)
        appmod.characters_for_user = dies
        try:
            appmod.socketio.test_client(appmod.app, flask_test_client=http)
        except Exception:
            pass                                        # (the old code crashed here: KeyError in join_room)
        finally:
            appmod.characters_for_user = real
        if how == 'closing':
            manager.disconnect(sids[0], '/')
        return sids[0]

    errors_before = sum(l.startswith('ERROR') for l in LOGS.lines)
    for how in ('closed', 'closing'):
        http_die, die1 = new_player(f'd1_{how}')
        _, die2 = new_player(f'd2_{how}')
        room, my_role, their_role = match_of(die1, die2)
        g = appmod.GAMES[room]
        me = g['players'][my_role]
        die1.disconnect()
        left_at = me['disconnected_at']
        die2.get_received()
        dead_sid = return_and_die(http_die, how)
        check(f"a connection that dies while rejoining doesn't take the seat ({how})",
              me['disconnected_at'] == left_at and me['id'] != dead_sid
              and appmod.DISCONNECTED_USERS.get(me['user_id']) == room,
              (me['disconnected_at'], left_at, appmod.DISCONNECTED_USERS))
        check(f"...leaves nothing behind for the dead connection ({how})", dead_sid not in appmod.SID_ROOM_MAP)
        check(f"...and the opponent isn't told they're back ({how})",
              not any(e['name'] == 'message' and 'RECONNECTED' in text(e) for e in die2.get_received()))
        die1 = appmod.socketio.test_client(appmod.app, flask_test_client=http_die)
        got = die1.get_received()
        check(f"...and the player can still come back in time ({how})",
              any(e['name'] == 'game-start' and e['args'][0] == {'roomId': room, 'role': my_role} for e in got)
              and me['disconnected_at'] is None and appmod.DISCONNECTED_USERS == {}, got)
        die1.disconnect()
        die2.get_received()
        return_and_die(http_die, how)
        with clock_ahead(appmod.RECONNECT_SECONDS + 1):
            check_disconnects()
        check(f"...or forfeits after the grace period if they stay away ({how})",
              g.get('winner') == their_role and room not in appmod.GAMES and appmod.DISCONNECTED_USERS == {},
              (g.get('winner'), appmod.DISCONNECTED_USERS))
        if room in appmod.GAMES:                        # (only if the check above failed)
            die2.emit('surrender', {})
        die2.disconnect()
    check("none of this is logged as an error", sum(l.startswith('ERROR') for l in LOGS.lines) == errors_before)

    # The other side of the race: the connection starts closing just AFTER it got its seat back. The
    # disconnect (another thread) waits for the match's lock and must then count as leaving again.
    http_late, late1 = new_player('late1')
    _, late2 = new_player('late2')
    room, my_role, their_role = match_of(late1, late2)
    g = appmod.GAMES[room]
    late1.disconnect()
    real_join, closers = appmod.join_room, []

    def join_then_close(*args, **kwargs):
        appmod.join_room = real_join
        sid = appmod.request.sid
        closers.append(threading.Thread(target=lambda: appmod.socketio.server.disconnect(sid)))
        closers[0].start()
        time.sleep(0.05)                                # it is now waiting for the lock we hold
        return real_join(*args, **kwargs)
    appmod.join_room = join_then_close
    try:
        late1 = appmod.socketio.test_client(appmod.app, flask_test_client=http_late)
    finally:
        appmod.join_room = real_join
    closers[0].join()
    check("a connection that closes right after rejoining counts as gone again (new grace period)",
          g['players'][my_role]['disconnected_at'] is not None
          and appmod.DISCONNECTED_USERS.get(g['players'][my_role]['user_id']) == room
          and g['players'][my_role]['id'] not in appmod.SID_ROOM_MAP, appmod.DISCONNECTED_USERS)
    with clock_ahead(appmod.RECONNECT_SECONDS + 1):
        check_disconnects()
    check("(cleanup) that match was forfeited", g.get('winner') == their_role and room not in appmod.GAMES)
    late2.disconnect()
    check("(cleanup) nothing is left of any of these matches", leftovers() == NOTHING, leftovers())

    # --- Step 41 regression (BE-15): on a real network the server hears that a connection closed AFTER the
    # same player's new one arrived (Render: 10 s later). The reloaded page stayed outside its match, and the
    # late goodbye then made the player lose although connected. ---
    def page_client(http, page):
        return appmod.socketio.test_client(appmod.app, flask_test_client=http, auth={'page': page})

    def paged_player(tag, page):
        http, client = new_player(tag)
        client.disconnect()
        client = page_client(http, page)
        client.get_received()
        return http, client

    def in_match(client, room_id, role):
        return any(e['name'] == 'game-start' and e['args'][0] == {'roomId': room_id, 'role': role}
                   for e in client.get_received())

    def told(client, words):
        return any(e['name'] == 'message' and words in text(e) for e in client.get_received())

    def can_play(client, other, g, role):
        # `client` really holds the seat: its commit is accepted (passing the opponent's turn first if needed)
        if g['turn'] != role:
            other.emit('commit-turn', {'paymentList': []})
        client.get_received()
        client.emit('commit-turn', {'paymentList': []})
        return g['turn'] != role and not any(e['name'] == 'error-msg' for e in client.get_received())

    def end_by_surrender(client, room_id):
        client.emit('surrender', {})
        return room_id not in appmod.GAMES

    http_r, page1 = paged_player('rel1', 'page-aaaa-1')
    _, opp = paged_player('rel2', 'page-bbbb-1')
    room, my_role, their_role = match_of(page1, opp)
    g = appmod.GAMES[room]
    me = g['players'][my_role]
    page2 = page_client(http_r, 'page-aaaa-1')              # the reloaded page; the old goodbye is still on its way
    page2_sid = sid_of(page2)
    got2 = page2.get_received()
    check("a reloaded page is back in its match at once, although the old connection still counts as open",
          any(e['name'] == 'game-start' and e['args'][0] == {'roomId': room, 'role': my_role} for e in got2)
          and any(e['name'] == 'update-state' for e in got2) and me['id'] == page2_sid, [e['name'] for e in got2])
    check("...the old page is told and closed", not page1.is_connected() and any(   # (get_received needs a connection)
        e['name'] == 'error-msg' and e['args'][0] == getattr(appmod, 'MOVED_MSG', None) for e in page1.queue))
    check("...the opponent notices nothing", not told(opp, 'DISCONNECTED'))
    check("...and the new page can play", can_play(page2, opp, g, my_role), g['turn'])
    if page1.is_connected():
        page1.disconnect()                                  # the late goodbye
    with clock_ahead(appmod.RECONNECT_SECONDS + 1):
        check_disconnects()
    check("...and the old connection's late goodbye costs nothing (no countdown, no forfeit)",
          room in appmod.GAMES and not g.get('winner') and me['disconnected_at'] is None
          and appmod.DISCONNECTED_USERS == {}, (g.get('winner'), appmod.DISCONNECTED_USERS))
    page3 = page_client(http_r, 'page-aaaa-1')
    page4 = page_client(http_r, 'page-aaaa-1')
    check("reloading twice quickly: the newest page has the seat",
          in_match(page4, room, my_role) and me['id'] == sid_of(page4) and can_play(page4, opp, g, my_role))

    # A second TAB (another page id) never takes a seat that is still connected...
    tab = page_client(http_r, 'page-tab-two')
    check("a second tab still doesn't take over a connected seat",
          not in_match(tab, room, my_role) and me['id'] == sid_of(page4))
    stored = []
    for bad in (None, 5, '', 'x', 'a' * 65, 'bad id!', ['page-aaaa-1'], {'page': 1}):
        weird = page_client(http_r, bad)
        stored.append(appmod.USER_SIDS[me['user_id']].get(sid_of(weird)))
        if in_match(weird, room, my_role):
            check(f"a malformed page id ({str(bad)[:12]!r}) takes no seat", False)
        weird.disconnect()
    check("malformed page ids take no seat", me['id'] == sid_of(page4))
    check("...and are never kept (a hostile page can't fill the server's memory)", set(map(repr, stored)) == {'None'}, stored)
    http_x, stranger = paged_player('rel3', 'page-aaaa-1')
    check("another account with the same page id gets nothing", not in_match(stranger, room, my_role)
          and me['id'] == sid_of(page4))
    stranger.disconnect()
    # ...but gets it when the seat's connection is gone (instead of a countdown against a connected player).
    opp.get_received()
    page4.disconnect()
    check("when the seat's connection dies, the account's other open page gets the match",
          in_match(tab, room, my_role) and me['id'] == sid_of(tab) and me['disconnected_at'] is None
          and appmod.DISCONNECTED_USERS == {}, (me['disconnected_at'], appmod.DISCONNECTED_USERS))
    check("...the opponent isn't told to wait", not told(opp, 'DISCONNECTED'))
    check("...and that page can play", can_play(tab, opp, g, my_role))
    tab.disconnect()
    check("when the last connection is gone the countdown starts as before",
          me['disconnected_at'] is not None and appmod.DISCONNECTED_USERS.get(me['user_id']) == room
          and told(opp, 'DISCONNECTED'))
    other_device = page_client(http_r, 'page-phone-1')
    check("...and any page of the account can still come back during it", in_match(other_device, room, my_role)
          and me['disconnected_at'] is None)

    # A dying connection is no heir: the countdown must start.
    spare = page_client(http_r, 'page-spare-1')
    spare_sid = sid_of(spare)
    appmod.socketio.server.manager.pre_disconnect(spare_sid, '/')
    other_device.disconnect()
    check("a connection that is closing itself doesn't inherit the seat",
          me['disconnected_at'] is not None and me['id'] != spare_sid and spare_sid not in appmod.SID_ROOM_MAP)
    appmod.socketio.server._trigger_event('disconnect', '/', spare_sid, 'test')
    appmod.socketio.server.manager.disconnect(spare_sid, '/')
    back = page_client(http_r, 'page-aaaa-1')
    back.get_received()

    # The real race, 20 times: the new page connects while the old connection's goodbye is being handled.
    lost = []
    for n in range(20):
        fresh = []
        at_once(lambda: fresh.append(page_client(http_r, 'page-aaaa-1')),
                lambda: back.is_connected() and back.disconnect())
        if not (me['id'] == sid_of(fresh[0]) and me['disconnected_at'] is None and appmod.DISCONNECTED_USERS == {}
                and appmod.SID_ROOM_MAP.get(sid_of(fresh[0])) == room):
            lost.append(n)
            break
        back = fresh[0]
    check("new page and old goodbye at the same instant, 20 rounds: the player always keeps the match", lost == [], lost)
    check("...and no connection is left over in the bookkeeping",
          sorted(appmod.SID_ROOM_MAP) == sorted([me['id'], g['players'][their_role]['id']]), appmod.SID_ROOM_MAP)
    check("no player is sent anybody's page id", not any(
        'page-aaaa-1' in repr(e) or 'page-bbbb-1' in repr(e) for c in (back, opp) for e in c.get_received())
        and me.get('page') == 'page-aaaa-1')
    check("(cleanup) that match ended", end_by_surrender(opp, room))
    late_page = page_client(http_r, 'page-aaaa-1')
    check("after the match, the same page id leads nowhere", not any(
        e['name'] == 'game-start' for e in late_page.get_received()) and leftovers() == NOTHING
        and getattr(appmod, 'USER_ROOMS', None) == {}, (leftovers(), getattr(appmod, 'USER_ROOMS', None)))
    for c in (back, late_page, opp):
        if c.is_connected():
            c.disconnect()

    # Logging out everywhere closes all pages: that IS leaving (no page inherits the seat for good).
    http_o, out1 = paged_player('out1', 'page-out-one')
    _, out2 = paged_player('out2', 'page-out-opp')
    room, my_role, their_role = match_of(out1, out2)
    g = appmod.GAMES[room]
    page_client(http_o, 'page-out-two')
    http_o.post('/api/logout')
    check("logging out everywhere with two pages open counts as leaving",
          g['players'][my_role]['disconnected_at'] is not None
          and appmod.DISCONNECTED_USERS.get(g['players'][my_role]['user_id']) == room)
    with clock_ahead(appmod.RECONNECT_SECONDS + 1):
        check_disconnects()
    check("(cleanup) forfeited, nothing left", g.get('winner') == their_role and leftovers() == NOTHING, leftovers())
    out2.disconnect()

    # --- Step 18 regression: there was no way to give up a match; the only way
    # out was leaving and waiting out the reconnect grace period. ---
    _, quit1 = new_player('quit1')
    _, quit2 = new_player('quit2')
    room, quit_role, other_role = match_of(quit1, quit2)
    g = appmod.GAMES[room]
    clients = {quit_role: quit1, other_role: quit2}
    if g['turn'] == quit_role:                      # surrender on the OPPONENT's turn
        quit1.emit('commit-turn', {'paymentList': []})
    quit_uid, other_uid = g['players'][quit_role]['user_id'], g['players'][other_role]['user_id']
    with appmod.app.app_context():
        before = {uid: (appmod.db.session.get(appmod.UserStats, uid).total_wins,
                        appmod.db.session.get(appmod.UserStats, uid).total_losses) for uid in (quit_uid, other_uid)}
    quit1.get_received(); quit2.get_received()
    quit1.emit('surrender', {})
    got1, got2 = quit1.get_received(), quit2.get_received()
    check("surrendering (even on the opponent's turn) ends the match for the opponent",
          g.get('winner') == other_role and room not in appmod.GAMES, (g.get('winner'), room in appmod.GAMES))
    check("...both players get the final state and the reason",
          all(any(e['name'] == 'update-state' and e['args'][0].get('winner') == other_role for e in got)
              and any(e['name'] == 'message' and 'SURRENDERED' in text(e) for e in got) for got in (got1, got2)))
    with appmod.app.app_context():
        after = {uid: (appmod.db.session.get(appmod.UserStats, uid).total_wins,
                       appmod.db.session.get(appmod.UserStats, uid).total_losses) for uid in (quit_uid, other_uid)}
    check("...the loss goes to the player who surrendered and the win to the opponent",
          after[quit_uid] == (before[quit_uid][0], before[quit_uid][1] + 1)
          and after[other_uid] == (before[other_uid][0] + 1, before[other_uid][1]), (before, after))
    quit1.emit('surrender', {})
    errors = [text(e) for e in quit1.get_received() if e['name'] == 'error-msg']
    check("surrendering again (no match any more) gets a clear answer", errors == ["You are not in a match."], errors)

    # Surrendering while the opponent is disconnected (in their grace period) ends it at once.
    http_gone, gone = new_player('gone1')
    _, stay = new_player('stay1')
    room, gone_role, stay_role = match_of(gone, stay)
    g = appmod.GAMES[room]
    gone.disconnect()
    stay.get_received()
    stay.emit('surrender', {})
    check("surrendering while the opponent is reconnecting ends the match in their favour",
          g.get('winner') == gone_role and room not in appmod.GAMES)
    check("...and leaves no reconnect bookkeeping behind", appmod.DISCONNECTED_USERS == {}, appmod.DISCONNECTED_USERS)
    for c in (quit1, quit2, stay):
        c.disconnect()

# --- Step 35: logging. Everything above ran with a capture on the root logger: the events
# needed to investigate bugs, matches and attacks must be there -- and no secret may be. ---
appmod.log_stats()
appmod.app.test_client().post('/api/login', json={'username': f'nobody_{suffix}', 'password': 'x'},
                                  environ_base={'REMOTE_ADDR': '198.51.100.99'})
logged = '\n'.join(LOGS.lines)
EXPECTED_LOG_EVENTS = {
    "account created": "INFO arena.auth: Account created: user=",
    "registration refused (with a reason)": "INFO arena.auth: Registration refused: reason=",
    "successful login": "INFO arena.auth: Login: user=",
    "failed login, wrong password": "WARNING arena.auth: Login failed: wrong password user=",
    "failed login, unknown account": "WARNING arena.auth: Login failed: unknown account name=",
    "rate limit hit": "WARNING arena.auth: Rate limit hit: too many",
    "logout everywhere": "INFO arena.auth: Logout (every device): user=",
    "an old cookie rejected after logout": "INFO arena.auth: Rejected a login cookie from before a logout-everywhere",
    "HTTP request with status + timing": "INFO arena.http: POST /api/register 201 ",
    "game connection": "INFO arena.socket: Connected: user=",
    "disconnection": "INFO arena.socket: Disconnected: user=",
    "matchmaking": "INFO arena.match: Searching: user=",
    "a search whose player already left": "INFO arena.match: Search dropped (disconnected): user=",
    "match start with teams + seed": "INFO arena.match: Match started: room=",
    "each committed turn with its moves": "INFO arena.match: Turn: room=",
    "a timed-out turn": "INFO arena.match: Turn timed out: room=",
    "a counter-trap": "INFO arena.match: Counter-trap fired: room=",
    "a player leaving mid-match": "INFO arena.match: Player left mid-match: room=",
    "a player rejoining": "INFO arena.match: Player rejoined: room=",
    "a seat moving to another connection": "INFO arena.match: Seat moved: room=",
    "a rejoin whose connection already died": "INFO arena.match: Rejoin dropped (disconnected): room=",
    "match end by KO": "cause=ko winner=",
    "match end by surrender": "cause=surrender winner=",
    "match end by timeouts": "cause=timeouts winner=",
    "match end by disconnect": "cause=disconnect winner=",
    "a bug, with its context and traceback": "ERROR app: Unhandled error in queue-skill: user=",
    "periodic health numbers": "INFO arena.stats: Stats: live_matches=",
}
missing = [what for what, needle in EXPECTED_LOG_EVENTS.items() if needle not in logged]
check(f"all {len(EXPECTED_LOG_EVENTS)} kinds of events are logged (accounts, security, requests, connections, "
      f"matches, turns, ends, bugs, stats)", missing == [], missing)
check("a logged bug carries its traceback", 'Traceback (most recent call last)' in logged)
check("a match start records the seed needed to replay it",
      any('Match started:' in l and 'rng_seed=' in l and 'team=' in l for l in LOGS.lines))
session_cookie = flask_client1.get_cookie('session')
secrets_in_logs = {
    'a password': 'testpass123' in logged,
    'the SECRET_KEY': appmod.settings.secret_key in logged,
    'a login cookie': bool(session_cookie) and session_cookie.value in logged,
    'an email address': '@test.local' in logged,
}
check(f"no secret or personal data in {len(LOGS.lines)} log lines (passwords, SECRET_KEY, cookies, emails)",
      not any(secrets_in_logs.values()), [k for k, v in secrets_in_logs.items() if v])
check("rule violations are logged at DEBUG, not as errors (no false alarms)",
      not any(l.startswith(('ERROR', 'WARNING')) and 'Refused ' in l for l in LOGS.lines))

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    raise SystemExit(1)
else:
    print("Integration smoke test passed.")
