"""
Real-browser end-to-end tests (Playwright, headless Chromium).

Starts the actual server (python app.py) on a free port with a throwaway
SQLite database, then drives two separate browser profiles through the real
UI exactly like two players would: register, pick a team, matchmake, play
turns (queue skills, pick targets, pay Ki in the payment dialog) until one
side wins. Also covers sessions and the disconnect/forfeit lifecycle.
Any JavaScript error in either browser fails the test.

Run with:  python test_browser_e2e.py
Needs:     pip install -r requirements-dev.txt && python -m playwright install chromium
Never touches backend/game.db.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BACKEND = os.path.dirname(os.path.abspath(__file__))
MAX_TURNS = 80
FAILURES = []
OPEN_PAGES = []  # (label, page) -- dumped as screenshots + battle logs when a test crashes
SURRENDER_ANSWERS = {}  # label -> True/False: how that player answers the "Surrender?" confirm

# Browser console messages that are expected, with the reason. They are counted
# and printed, never silently dropped. Anything else fails the test.
KNOWN_CONSOLE_NOISE = {
    'status of 401': "GET /api/me answers 401 when logged out -- that's how the frontend detects it (audit FE note)",
    'Invalid frame header': "dev server (Werkzeug) closing a WebSocket on page reload/logout; prod uses gunicorn+gevent",
}


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


# --- server -------------------------------------------------------------------

def start_server(tmp, name='server', **extra_env):
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    env = dict(os.environ, PORT=str(port), **extra_env,
               DATABASE_URL='sqlite:///' + os.path.join(tmp, f'{name}.db').replace('\\', '/'))
    log = open(os.path.join(tmp, f'{name}.log'), 'w', encoding='utf-8')
    proc = subprocess.Popen([sys.executable, 'app.py'], cwd=BACKEND, env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}'
    for _ in range(100):
        try:
            urllib.request.urlopen(url + '/', timeout=1)
            return proc, url, log
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
    proc.kill()
    log.close()
    raise RuntimeError("server didn't start; see " + os.path.join(tmp, f'{name}.log'))


# --- player actions (UI only) -------------------------------------------------

def new_player(browser, url, errors, label):
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(10_000)
    page.on('pageerror', lambda e: errors.append(f'{label}: {e}'))
    page.on('console', lambda m: m.type == 'error' and errors.append(f'{label} console: {m.text}'))
    page.on('framenavigated', lambda f: f == page.main_frame and errors.append(f'{label} --- navigated ---'))
    page.on('dialog', lambda d: answer_dialog(d, label, errors))
    # Everything must come from our own server (no third-party scripts; Step 21).
    own_host = urlparse(url).netloc
    page.on('request', lambda r: urlparse(r.url).netloc not in (own_host, '')
            and errors.append(f'{label} third-party request: {r.url}'))
    OPEN_PAGES.append((label, page))
    page.goto(url)
    name = f'{label}_{uuid.uuid4().hex[:6]}'
    # First load fetches socket.io from a CDN (audit SEC-8) and then checks the session -- wait for the form.
    page.wait_for_selector('#login-form a', state='visible', timeout=30_000)
    page.click('#login-form a')
    page.fill('#register-username', name)
    page.fill('#register-email', f'{name}@e2e.local')
    page.fill('#register-password', 'e2e-password')
    page.click('#register-form .big-btn')
    page.wait_for_selector('#lobby-screen', state='visible')
    page.wait_for_function("document.querySelectorAll('#char-grid .select-card').length >= 3")
    return context, page, name


def answer_dialog(dialog, label, errors):
    """The surrender confirm is expected and answered as the test says; any
    other dialog (e.g. a stray alert) is unexpected and fails the test."""
    if dialog.type == 'confirm' and dialog.message.startswith('Surrender') and label in SURRENDER_ANSWERS:
        dialog.accept() if SURRENDER_ANSWERS[label] else dialog.dismiss()
        return
    errors.append(f'{label} dialog: {dialog.message}')
    dialog.dismiss()


def find_match(page, card_indexes):
    cards = page.locator('#char-grid .select-card')
    for i in card_indexes:
        cards.nth(i).click()
    page.click('#find-match-btn')


def status(page):
    return page.locator('#status').inner_text()


def game_over(page):
    return status(page) in ('YOU WIN!', 'YOU LOSE!')


def is_my_turn(page):
    return page.locator('#end-turn').is_visible()


def queue_skills(page):
    """For each of my characters, queue its first usable skill (damage first)."""
    queued = 0
    for i in range(page.locator('#my-team .char-card').count()):
        if game_over(page):  # a counter-trap can end the match mid-queue
            break
        card = page.locator('#my-team .char-card').nth(i)
        buttons = card.locator('.skill-btn:not([disabled])')
        if buttons.count() == 0:
            continue
        texts = [buttons.nth(j).inner_text() for j in range(buttons.count())]
        order = sorted(range(len(texts)), key=lambda j: 'Dmg' not in texts[j])
        buttons.nth(order[0]).click()
        instruction = page.locator('#instruction').inner_text()
        # Click the portrait like a player would: the middle of your own card is
        # covered by skill buttons, which would select another skill instead.
        if 'ENEMY' in instruction:
            target = page.locator('#enemy-team .char-card:not(.dead) .char-img').first
        else:  # ally / self skills: this same character
            target = page.locator('#my-team .char-card').nth(i).locator('.char-img')
        log_lines = page.locator('#log div').count()
        # Status badges sit over the top-right of the portrait (UI_PLAN #8), so
        # aim at the lower-left corner, the part a player can still click.
        target.click(position={'x': 12, 'y': 100})
        # The server answers with either a new state (cancel button appears) or an error line.
        page.wait_for_function(
            f"document.querySelectorAll('#my-team .char-card')[{i}].querySelector('.cancel-btn')"
            f" || document.querySelectorAll('#log div').length > {log_lines}")
        queued += page.locator('#my-team .char-card').nth(i).locator('.cancel-btn').count()
    return queued


def end_turn(page):
    page.click('#end-turn')
    if page.locator('#payment-modal[open]').count():
        while page.locator('#confirm-payment-btn').is_disabled():
            page.locator('#available-payment-dice .die').first.click()
        page.click('#confirm-payment-btn')


def wait_for_turn_change(pages, previous):
    deadline = time.time() + 10
    while time.time() < deadline:
        if any(game_over(p) for p in pages):
            return
        if not is_my_turn(previous):
            return
        time.sleep(0.05)
    raise TimeoutError("turn did not pass")


def real_errors(errors):
    """Splits collected messages into unexpected ones and counted known noise.
    WebSocket teardown noise only counts as known if a navigation (reload/logout)
    happened in that browser -- during uninterrupted play it is a real error."""
    unexpected, noise, navigated = [], {}, set()
    for e in errors:
        label = e.split(' ', 1)[0]
        if e.endswith('--- navigated ---'):
            navigated.add(label)
            continue
        key = next((k for k in KNOWN_CONSOLE_NOISE if k in e), None)
        if key and (key != 'Invalid frame header' or label in navigated):
            noise[key] = noise.get(key, 0) + 1
        else:
            unexpected.append(e)
    for key, n in noise.items():
        print(f"    (known console noise x{n}: {KNOWN_CONSOLE_NOISE[key]})")
    return unexpected


# --- tests ----------------------------------------------------------------------

def test_full_match(browser, url):
    errors = []
    ctx1, p1, name1 = new_player(browser, url, errors, 'alpha')
    ctx2, p2, name2 = new_player(browser, url, errors, 'beta')
    check("two players register through the UI and reach the lobby", True)

    find_match(p1, [0, 1, 2])
    find_match(p2, [2, 3, 4])
    p1.wait_for_selector('#game-screen', state='visible')
    p2.wait_for_selector('#game-screen', state='visible')
    pages = [p1, p2]
    p1.wait_for_function("document.querySelectorAll('#my-team .char-card').length === 3")
    p2.wait_for_function("document.querySelectorAll('#my-team .char-card').length === 3")
    check("matchmaking pairs them and both see the battle board",
          p1.locator('#enemy-team .char-card').count() == 3 and p2.locator('#enemy-team .char-card').count() == 3)
    check("exactly one player has the turn", is_my_turn(p1) != is_my_turn(p2))
    check("both players see the turn countdown",
          all('turn ends in' in p.locator('#turn-timer').inner_text() for p in pages),
          [p.locator('#turn-timer').inner_text() for p in pages])

    turns, moves = 0, 0
    while turns < MAX_TURNS and not any(game_over(p) for p in pages):
        active = p1 if is_my_turn(p1) else p2
        moves += queue_skills(active)
        if any(game_over(p) for p in pages):
            break  # e.g. a hidden counter-trap killed the last character while queueing
        end_turn(active)
        wait_for_turn_change(pages, active)
        turns += 1

    print(f"    (match lasted {turns} turns, {moves} skills queued)")
    check(f"the match is played to a finish within {MAX_TURNS} turns", any(game_over(p) for p in pages),
          f"after {turns} turns")
    for p in pages:
        p.wait_for_function("['YOU WIN!', 'YOU LOSE!'].includes(document.getElementById('status').innerText)")
    results = {status(p1), status(p2)}
    check("one player sees YOU WIN! and the other YOU LOSE!", results == {'YOU WIN!', 'YOU LOSE!'}, results)
    check("skills were actually used during the match", moves > 0, moves)

    winner, loser = (p1, p2) if status(p1) == 'YOU WIN!' else (p2, p1)
    winner.wait_for_function("document.getElementById('user-badge-text').innerText.includes('W:1')")
    loser.wait_for_function("document.getElementById('user-badge-text').innerText.includes('L:1')")
    check("the result is saved and shown in both players' stats badge (W:1 / L:1)", True)
    unexpected = real_errors(errors)
    check("no JavaScript errors or alerts in either browser", unexpected == [], unexpected)
    ctx1.close()
    ctx2.close()


def test_session_survives_reload_and_logout_works(browser, url):
    errors = []
    ctx, page, name = new_player(browser, url, errors, 'gamma')
    page.reload()
    page.wait_for_selector('#lobby-screen', state='visible')
    check("the login session survives a page reload", name in page.locator('#user-badge-text').inner_text())
    page.click('#topbar a')
    page.wait_for_selector('#auth-screen', state='visible')
    check("logging out returns to the login screen", page.locator('#login-form').is_visible())
    unexpected = real_errors(errors)
    check("no JavaScript errors", unexpected == [], unexpected)
    ctx.close()


def test_disconnect_forfeits_to_opponent(browser, url):
    errors = []
    ctx1, p1, _ = new_player(browser, url, errors, 'delta')
    ctx2, p2, _ = new_player(browser, url, errors, 'epsilon')
    find_match(p1, [0, 1, 2])
    find_match(p2, [0, 1, 2])
    p1.wait_for_selector('#game-screen', state='visible')
    p2.wait_for_selector('#game-screen', state='visible')
    ctx2.close()  # player 2 closes the tab mid-match and never comes back
    p1.wait_for_function("document.getElementById('log').innerText.includes('DISCONNECTED -- waiting')")
    check("when the opponent disconnects, the remaining player is told they have time to come back",
          status(p1) != 'YOU WIN!')
    p1.wait_for_function("document.getElementById('status').innerText === 'YOU WIN!'", timeout=20_000)
    check("...and once the grace period runs out, the remaining player wins", True)
    check("...and is told why", "DIDN'T COME BACK IN TIME" in p1.locator('#log').inner_text())
    check("no JavaScript errors in the remaining player's browser",
          real_errors([e for e in errors if e.startswith('delta')]) == [], errors)
    ctx1.close()


def test_idle_player_times_out_and_forfeits(browser, url):
    """Runs against a server with a 2-second turn limit: nobody acts, so turns
    pass on their own (the real background ticker) until the player who never
    moves has timed out 3 times in a row and forfeits."""
    errors = []
    ctx1, p1, _ = new_player(browser, url, errors, 'zeta')
    ctx2, p2, _ = new_player(browser, url, errors, 'eta')
    find_match(p1, [0, 1, 2])
    find_match(p2, [0, 1, 2])
    p1.wait_for_selector('#game-screen', state='visible')
    p2.wait_for_selector('#game-screen', state='visible')
    p1.wait_for_function("document.getElementById('turn-timer').innerText.includes('turn ends in')")
    check("the countdown is shown", True)
    for p in (p1, p2):
        p.wait_for_function("['YOU WIN!', 'YOU LOSE!'].includes(document.getElementById('status').innerText)",
                            timeout=45_000)
    check("with nobody acting, turns pass on their own until someone forfeits",
          {status(p1), status(p2)} == {'YOU WIN!', 'YOU LOSE!'}, (status(p1), status(p2)))
    logs = p1.locator('#log').inner_text() + p2.locator('#log').inner_text()
    check("players are told each time a turn ran out", 'ran out of time' in logs)
    check("...and that the match ended by forfeit", 'FORFEITS' in logs)
    check("the countdown disappears when the match is over",
          p1.locator('#turn-timer').inner_text() == '' and p2.locator('#turn-timer').inner_text() == '')
    unexpected = real_errors(errors)
    check("no JavaScript errors", unexpected == [], unexpected)
    ctx1.close()
    ctx2.close()


def test_reload_mid_match_returns_to_the_match(browser, url):
    """BE-2: reloading the page used to forfeit the match on the spot."""
    errors = []
    ctx1, p1, _ = new_player(browser, url, errors, 'theta')
    ctx2, p2, _ = new_player(browser, url, errors, 'iota')
    find_match(p1, [0, 1, 2])
    find_match(p2, [2, 3, 4])
    for p in (p1, p2):
        p.wait_for_selector('#game-screen', state='visible')
        p.wait_for_function("document.querySelectorAll('#my-team .char-card').length === 3")
    my_names = p1.locator('#my-team .char-card').all_inner_texts()
    p1.reload()
    p1.wait_for_selector('#game-screen', state='visible')
    p1.wait_for_function("document.querySelectorAll('#my-team .char-card').length === 3")
    check("after a reload mid-match the player is back on the battle board",
          p1.locator('#lobby-screen').is_hidden() and status(p1) in ('PLAN YOUR MOVES', 'OPPONENT THINKING...'),
          status(p1))
    check("...with the same team", [t.split('\n')[0] for t in p1.locator('#my-team .char-card').all_inner_texts()]
          == [t.split('\n')[0] for t in my_names])
    p2.wait_for_function("document.getElementById('log').innerText.includes('RECONNECTED')")
    check("...and the opponent is told they're back", True)
    active = p1 if is_my_turn(p1) else p2
    end_turn(active)
    wait_for_turn_change([p1, p2], active)
    check("...and the match carries on (a turn passes normally)", not is_my_turn(active) and not game_over(p1))
    unexpected = real_errors(errors)
    check("no JavaScript errors", unexpected == [], unexpected)
    ctx1.close()
    ctx2.close()


def test_surrender_with_confirmation(browser, url):
    """BE-4: a Surrender button, behind a confirm dialog, ends the match as a loss."""
    errors = []
    ctx1, p1, _ = new_player(browser, url, errors, 'kappa')
    ctx2, p2, _ = new_player(browser, url, errors, 'lambda')
    find_match(p1, [0, 1, 2])
    find_match(p2, [2, 3, 4])
    for p in (p1, p2):
        p.wait_for_selector('#game-screen', state='visible')
        p.wait_for_function("document.querySelectorAll('#my-team .char-card').length === 3")
    check("both players see a Surrender button during the match",
          p1.locator('#surrender-btn').is_visible() and p2.locator('#surrender-btn').is_visible())

    SURRENDER_ANSWERS['kappa'] = False             # changes their mind
    p1.click('#surrender-btn')
    p1.wait_for_timeout(500)
    check("answering 'Cancel' keeps the match going", not game_over(p1) and not game_over(p2))

    SURRENDER_ANSWERS['kappa'] = True
    p1.click('#surrender-btn')
    for p in (p1, p2):
        p.wait_for_function("['YOU WIN!', 'YOU LOSE!'].includes(document.getElementById('status').innerText)")
    check("confirming ends the match: the one who surrendered loses, the opponent wins",
          (status(p1), status(p2)) == ('YOU LOSE!', 'YOU WIN!'), (status(p1), status(p2)))
    check("...both are told it was a surrender",
          'SURRENDERED' in p1.locator('#log').inner_text() and 'SURRENDERED' in p2.locator('#log').inner_text())
    p1.wait_for_function("document.getElementById('user-badge-text').innerText.includes('L:1')")
    p2.wait_for_function("document.getElementById('user-badge-text').innerText.includes('W:1')")
    check("...the result is saved (L:1 / W:1 badges)", True)
    check("...and the button disappears", p1.locator('#surrender-btn').is_hidden() and p2.locator('#surrender-btn').is_hidden())
    unexpected = real_errors(errors)
    check("no JavaScript errors or unexpected dialogs", unexpected == [], unexpected)
    ctx1.close()
    ctx2.close()


TESTS = [test_full_match, test_session_survives_reload_and_logout_works, test_reload_mid_match_returns_to_the_match,
         test_surrender_with_confirmation]
# Run on a second server with short limits (TURN_SECONDS=2, RECONNECT_SECONDS=3) so they finish quickly.
FAST_TIMER_TESTS = [test_idle_player_times_out_and_forfeits, test_disconnect_forfeits_to_opponent]

if __name__ == '__main__':
    tmp = tempfile.mkdtemp(prefix='dba_e2e_')
    proc, url, log = start_server(tmp)
    fast_proc, fast_url, fast_log = start_server(tmp, name='fast_timer_server', TURN_SECONDS='2',
                                                 RECONNECT_SECONDS='3')
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for t, t_url in [(t, url) for t in TESTS] + [(t, fast_url) for t in FAST_TIMER_TESTS]:
                print(f"{t.__name__}:")
                try:
                    t(browser, t_url)
                except Exception as e:
                    FAILURES.append(t.__name__)
                    print(f"  FAIL: {t.__name__} raised {type(e).__name__}: {str(e).splitlines()[0]}")
                    for label, page in OPEN_PAGES:
                        if page.is_closed():
                            continue
                        shot = os.path.join(tmp, f'{t.__name__}_{label}.png')
                        page.screenshot(path=shot, full_page=True)
                        log_text = ' | '.join(page.locator('#log').inner_text()[-600:].splitlines())
                        print(f"    {label}: status={page.locator('#status').inner_text()!r} "
                              f"instruction={page.locator('#instruction').inner_text()!r} screenshot={shot}")
                        print(f"    {label} log: {log_text}")
                OPEN_PAGES.clear()
            browser.close()
    finally:
        for server, server_log in ((proc, log), (fast_proc, fast_log)):
            server.terminate()
            server.wait(timeout=10)
            server_log.close()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}\nServer log: {os.path.join(tmp, 'server.log')}")
        raise SystemExit(1)
    print(f"All {len(TESTS) + len(FAST_TIMER_TESTS)} browser test functions passed.")
