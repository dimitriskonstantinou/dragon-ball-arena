"""
Load generator: N bot players play real matches against a running server (DEPLOY_PLAN Stage 5).
Usually started by tools/run_loadtest.py, which also runs the server and measures it.

    python tools/loadtest.py --url http://server:8000 --levels 100,500,1000 --seconds 90

Each bot registers (once), connects over a websocket with its own login cookie, searches for
a match and plays like a (fast) player: after 2-4 s it queues one affordable skill on a valid
target, pays the exact Ki and commits; it surrenders after 8-20 of its turns and searches again,
so matches keep starting and ending. Prints one JSON line per phase:
  {"phase": "register", ...}  {"phase": "level", "players": N, "latency_ms": {...}, ...}
Needs: pip install -r tools/requirements-loadtest.txt
"""
import argparse
import asyncio
import json
import random
import time
import uuid
from collections import Counter

import aiohttp
import socketio

SERVER_ERROR = "Something went wrong on the server"
THINK = (2.0, 4.0)
SURRENDER_AFTER = (8, 20)
ACK_TIMEOUT = 15.0


def pay(cost, pool):
    """Exact payment for `cost` from the dice in `pool` (specific types first, then any for 'random'), or None."""
    pool, out = list(pool), []
    for kind, n in cost.items():
        if kind == 'random':
            continue
        for _ in range(n):
            if kind not in pool:
                return None
            pool.remove(kind)
            out.append(kind)
    need = cost.get('random', 0)
    if len(pool) < need:
        return None
    return out + pool[:need]


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))], 1)


class Stats:
    def __init__(self):
        self.reset()

    def reset(self):
        self.started = time.time()
        self.cpu_started = time.process_time()
        self.commit_ms, self.queue_ms = [], []
        self.turns = self.matches_started = self.matches_ended = 0
        self.errors = Counter()            # refusals by message (rules: stunned, ...)
        self.server_errors = 0             # the generic "something went wrong" = a server bug
        self.lost_acks = self.unexpected_disconnects = self.connect_failures = 0
        self.refused_commits = self.counter_trapped = 0

    def summary(self, players):
        secs = time.time() - self.started
        return {
            'players': players, 'seconds': round(secs, 1), 'start': round(self.started, 1), 'end': round(time.time(), 1),
            # The generator is one process: near 100% its own delays would be reported as the server's.
            'generator_cpu': round(100 * (time.process_time() - self.cpu_started) / secs) if secs else 0,
            'turns': self.turns, 'turns_per_s': round(self.turns / secs, 1) if secs else 0,
            'matches_started': self.matches_started, 'matches_ended': self.matches_ended,
            'latency_ms': {'commit_p50': percentile(self.commit_ms, 50), 'commit_p95': percentile(self.commit_ms, 95),
                           'commit_p99': percentile(self.commit_ms, 99),
                           'commit_max': round(max(self.commit_ms), 1) if self.commit_ms else None,
                           'queue_p50': percentile(self.queue_ms, 50), 'queue_p95': percentile(self.queue_ms, 95)},
            'server_errors': self.server_errors, 'lost_acks': self.lost_acks,
            'refused_commits': self.refused_commits, 'counter_trapped': self.counter_trapped,
            'unexpected_disconnects': self.unexpected_disconnects, 'connect_failures': self.connect_failures,
            'refusals': dict(self.errors.most_common(5)),
        }


class Bot:
    def __init__(self, url, name, stats):
        self.url, self.name, self.stats = url, name, stats
        self.password = 'loadtest-' + uuid.uuid4().hex[:10]
        self.cookie = None
        self.sio = None
        self.characters = []
        self.role = self.state = None
        self.acted_turn = None
        self.my_turns = 0
        self.surrender_after = random.randint(*SURRENDER_AFTER)
        self.ack = asyncio.Event()
        self.ack_error = None
        self.commit_started = None
        self.stopping = False

    async def register(self, http):
        async with http.post(f'{self.url}/api/register', json={
                'username': self.name, 'email': f'{self.name}@loadtest.invalid', 'password': self.password}) as r:
            if r.status != 201:
                raise RuntimeError(f'register {r.status}')
            # The cookie is Secure in production and this test talks plain http inside Docker,
            # so it's taken from the header instead of a cookie jar.
            for header in r.headers.getall('Set-Cookie', []):
                if header.startswith('session='):
                    self.cookie = header.split(';', 1)[0]

    async def connect(self):
        self.role = self.state = self.acted_turn = self.commit_started = None
        self.sio = socketio.AsyncClient(reconnection=False)
        s = self.sio
        s.on('character-list', self.on_characters)
        s.on('game-start', self.on_game_start)
        s.on('update-state', self.on_state)
        s.on('error-msg', self.on_error)
        s.on('disconnect', self.on_disconnect)
        await s.connect(self.url, headers={'Cookie': self.cookie}, transports=['websocket'], wait_timeout=20)
        # The server sends the roster DURING the handshake, before the client counts as connected,
        # so the first search happens here.
        await self.search()

    async def on_characters(self, chars):
        self.characters = [c['id'] for c in chars]

    async def search(self):
        # A role means the server put us back into an unfinished match (reconnect): play that one.
        if self.stopping or self.role or len(self.characters) < 3 or not (self.sio and self.sio.connected):
            return
        self.role = self.state = self.acted_turn = None
        self.my_turns = 0
        await self.sio.emit('find-match', random.sample(self.characters, 3))

    async def on_game_start(self, data):
        self.role = data['role']
        if self.role == 'p1':
            self.stats.matches_started += 1

    async def on_error(self, msg):
        if SERVER_ERROR in msg:
            self.stats.server_errors += 1
        else:
            self.stats.errors[msg[:60]] += 1
        if self.commit_started:              # a refused commit: no response time to measure
            self.commit_started = None
            self.stats.refused_commits += 1
        self.ack_error = msg
        self.ack.set()

    async def on_disconnect(self, *args):
        if not self.stopping:
            self.stats.unexpected_disconnects += 1

    async def on_state(self, state):
        self.state = state
        self.ack.set()
        if self.commit_started and (state.get('winner') or state.get('turn') != self.role):
            self.stats.commit_ms.append((time.perf_counter() - self.commit_started) * 1000)
            self.stats.turns += 1
            self.commit_started = None
        if state.get('winner'):
            if self.role == 'p1':
                self.stats.matches_ended += 1
            self.role = None
            asyncio.get_running_loop().call_later(random.uniform(1, 2), lambda: asyncio.ensure_future(self.search()))
            return
        if self.role and state.get('turn') == self.role and state.get('turn_count') != self.acted_turn:
            self.acted_turn = state.get('turn_count')
            asyncio.ensure_future(self.play_turn(self.acted_turn))

    async def wait_ack(self):
        try:
            await asyncio.wait_for(self.ack.wait(), ACK_TIMEOUT)
            return True
        except asyncio.TimeoutError:
            self.stats.lost_acks += 1
            return False

    def choose(self):
        me, them = self.state['players'][self.role], self.state['players']['p2' if self.role == 'p1' else 'p1']
        pool = me.get('resources', [])
        live_enemies = [i for i, c in enumerate(them['team']) if c['health'] > 0]
        options = []
        for idx, char in enumerate(me['team']):
            if char['health'] <= 0:
                continue
            for skill in char.get('skills', []):
                if skill.get('currentCooldown', 0) > 0 or skill.get('locked'):
                    continue
                payment = pay(skill.get('cost', {}), pool)
                if payment is None:
                    continue
                kind = skill.get('target_type', 'enemy')
                if kind == 'enemy':
                    targets = [i for i in live_enemies if skill.get('ignores_invulnerable') or not any(
                        'invulnerable' in s.get('type', '') for s in them['team'][i].get('status', []))]
                    if not targets:
                        continue
                    target = (('p2' if self.role == 'p1' else 'p1'), random.choice(targets))
                elif kind == 'enemy_team':
                    target = (('p2' if self.role == 'p1' else 'p1'), live_enemies[0])
                else:   # self / ally / ally_team
                    target = (self.role, idx)
                options.append((char['id'], skill['id'], target, payment))
        return random.choice(options) if options else None

    async def play_turn(self, turn_count):
        try:
            await self.take_turn(turn_count)
        except socketio.exceptions.BadNamespaceError:   # disconnected while thinking (level over)
            if not self.stopping:
                raise

    async def take_turn(self, turn_count):
        await asyncio.sleep(random.uniform(*THINK))
        if self.stopping or not self.state or self.state.get('turn_count') != turn_count or self.role is None:
            return
        self.my_turns += 1
        if self.my_turns > self.surrender_after:
            await self.sio.emit('surrender', {})
            return
        payment = []
        choice = self.choose()
        if choice:
            char_id, skill_id, (pkey, index), cost_dice = choice
            self.ack.clear()
            self.ack_error = None
            started = time.perf_counter()
            await self.sio.emit('queue-skill', {'charId': char_id, 'skillId': skill_id,
                                                'targetPlayerKey': pkey, 'targetIndex': index})
            if await self.wait_ack():
                self.stats.queue_ms.append((time.perf_counter() - started) * 1000)
                # Pay only for what the server actually queued (like the real client): a counter-trap
                # cancels the move without an error -- paying for it would be refused.
                queued = [m for m in (self.state or {}).get('pending_moves', []) if m.get('charId') == char_id]
                if not self.ack_error and queued:
                    payment = cost_dice
                elif not self.ack_error:
                    self.stats.counter_trapped += 1
            await asyncio.sleep(random.uniform(0.3, 1.0))
        if self.stopping or not self.state or self.state.get('turn') != self.role:
            return
        self.commit_started = time.perf_counter()
        self.ack.clear()
        await self.sio.emit('commit-turn', {'paymentList': payment})

    async def stop(self):
        self.stopping = True
        try:
            if self.role:
                await self.sio.emit('surrender', {})
                # Leave only once the match is over, or the next level starts inside old matches.
                for _ in range(200):
                    if not self.role:
                        break
                    await asyncio.sleep(0.1)
            await self.sio.disconnect()
        except Exception:
            pass


async def register_all(url, count, stats):
    bots, failures = [], 0
    prefix = 'lt' + uuid.uuid4().hex[:5]
    sem = asyncio.Semaphore(32)
    started = time.time()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as http:
        async def one(i):
            nonlocal failures
            bot = Bot(url, f'{prefix}{i}', stats)
            async with sem:
                try:
                    await bot.register(http)
                    bots.append(bot)
                except Exception:
                    failures += 1
        await asyncio.gather(*(one(i) for i in range(count)))
    secs = time.time() - started
    print(json.dumps({'phase': 'register', 'accounts': len(bots), 'failures': failures, 'seconds': round(secs, 1),
                      'per_second': round(len(bots) / secs, 1) if secs else 0}), flush=True)
    return bots


async def run_level(bots, seconds, ramp, stats):
    """Connects `bots` over `ramp` seconds, then measures `seconds` of play."""
    async def start(bot, delay):
        await asyncio.sleep(delay)
        bot.stopping = False
        try:
            await bot.connect()
        except Exception:
            stats.connect_failures += 1
    stats.reset()
    await asyncio.gather(*(start(b, ramp * i / max(1, len(bots))) for i, b in enumerate(bots)))
    await asyncio.sleep(10)          # matches get going
    stats.reset()
    connect_failures = sum(1 for b in bots if not (b.sio and b.sio.connected))
    await asyncio.sleep(seconds)
    result = stats.summary(len(bots))
    result['connected'] = len(bots) - connect_failures
    result['connected_at_end'] = sum(1 for b in bots if b.sio and b.sio.connected)
    now = time.perf_counter()
    result['unanswered_commits'] = sum(1 for b in bots if b.commit_started and now - b.commit_started > ACK_TIMEOUT)
    print(json.dumps({'phase': 'level', **result}), flush=True)
    await asyncio.gather(*(b.stop() for b in bots))
    await asyncio.sleep(5)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--levels', default='100,500,1000,2000')
    ap.add_argument('--seconds', type=int, default=90, help='measured seconds per level')
    ap.add_argument('--ramp', type=int, default=30, help='seconds to connect all bots of a level')
    ap.add_argument('--think', default='2,4', help='seconds a bot waits before acting: min,max')
    args = ap.parse_args()
    global THINK
    THINK = tuple(float(x) for x in args.think.split(','))
    levels = [int(x) for x in args.levels.split(',')]
    stats = Stats()
    bots = await register_all(args.url, max(levels), stats)
    for n in levels:
        if n > len(bots):
            break
        print(json.dumps({'phase': 'level_start', 'players': n, 'at': round(time.time(), 1)}), flush=True)
        await run_level(bots[:n], args.seconds, args.ramp, stats)
    print(json.dumps({'phase': 'done'}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
