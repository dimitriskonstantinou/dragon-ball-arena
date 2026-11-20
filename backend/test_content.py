"""
Content pipeline tests: backend/content/ files, content_schema.py models and
content_loader.py checks. Run with: python test_content.py

Covers the real roster (loads, schema files current, every skill can be cast
in a sandbox match) and crafted invalid content (malformed JSON, unknown
fields/effects, boundaries, broken cross-references) to prove bad content is
rejected with a useful message instead of loading silently.
"""
import copy
import json
import os
import re
import tempfile

import content_loader as cl
import content_schema as cs
import game_engine as ge

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


# --- helpers ------------------------------------------------------------------

SHARED = {'abilities': {'afterimage_technique': {
    'id': 'afterimage_technique', 'name': 'Afterimage Technique', 'description': 'Immune for 1 turn',
    'cost': {'random': 1}, 'target_type': 'self', 'effects': [{'type': 'invulnerable', 'duration': 1}],
    'cooldown': 4}}}


def valid_char(cid='test_char'):
    """Smallest valid character, using images that exist on disk."""
    return {
        'id': cid, 'name': 'Test', 'image': 'characters/Goku_(Saiyan-Saga).png', 'health': 100,
        'skills': [
            {'id': 'hit', 'name': 'Hit', 'description': '10 Dmg', 'cost': {'energy': 1}, 'target_type': 'enemy',
             'image': 'Goku_(Saiyan-Saga)_Kamehameha.png', 'effects': [{'type': 'damage', 'value': 10}],
             'cooldown': 0},
            {'use': 'afterimage_technique', 'name': 'Block'},
        ],
    }


def load(chars, shared=SHARED, raw_files=None):
    """Writes a temporary content dir and loads it. Returns (catalog, problems)."""
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, 'characters'))
        if shared is not None:
            with open(os.path.join(tmp, 'shared_abilities.json'), 'w', encoding='utf-8') as fh:
                json.dump(shared, fh)
        for c in chars:
            with open(os.path.join(tmp, 'characters', f"{c['id']}.json"), 'w', encoding='utf-8') as fh:
                json.dump(c, fh)
        for name, text in (raw_files or {}).items():
            with open(os.path.join(tmp, 'characters', name), 'w', encoding='utf-8') as fh:
                fh.write(text)
        try:
            return cl.load_catalog(content_dir=tmp), []
        except cl.ContentError as e:
            return None, e.problems


def rejected(name, chars, expect, **kw):
    """Checks that loading fails and some problem message contains `expect`."""
    _, problems = load(chars, **kw)
    check(name, any(expect in p for p in problems), problems)


def with_skill(**changes):
    c = valid_char()
    c['skills'][0].update(changes)
    return c


def with_effect(effect, extra_skills=()):
    c = with_skill(effects=[effect])
    c['skills'][1:1] = list(extra_skills)
    return c


# --- the real roster ----------------------------------------------------------

def test_real_content_loads():
    catalog = cl.load_catalog()
    check("the real content loads with no problems", len(catalog) >= 1, len(catalog))
    check("character ids are saga-style lowercase ids", all(re.fullmatch(r'[a-z0-9_]+', c) for c in catalog))
    leaked = [(cid, s['id']) for cid, c in catalog.items() for s in c['skills'] if 'notes' in s]
    check("author-only notes never reach the game data", leaked == [] and not any('notes' in c for c in catalog.values()),
          leaked)
    check("runtime fields are filled in (currentCooldown, maxHealth, status)",
          all(s['currentCooldown'] == 0 for c in catalog.values() for s in c['skills'])
          and all(c['maxHealth'] == c['health'] and c['status'] == [] for c in catalog.values()))
    check("catalog() loads once and is shared (same object every call)",
          cl.catalog() is cl.catalog() and cl.catalog() == catalog)


def test_schema_files_are_current():
    """The VS Code schema files must match the Pydantic models."""
    for name, schema in cs.build_schemas().items():
        with open(os.path.join(cs.CONTENT_DIR, name), encoding='utf-8') as fh:
            on_disk = json.load(fh)
        check(f"{name} is up to date (else run: python content_schema.py)", on_disk == schema)


def test_models_cover_exactly_the_engine_effects():
    src = open(ge.__file__, encoding='utf-8').read()
    body = src[src.index('def apply_effect('):src.index('# --- per-player view')]
    engine = set()
    for cond in re.findall(r"\n    (?:el)?if (etype [^\n]+):", body):
        engine.update(re.findall(r"'(\w+)'", cond))
    models = cs.effect_types()
    check("every engine effect type has a content model", engine - models == set(), engine - models)
    check("no content model exists for an effect the engine doesn't implement", models - engine == set(),
          models - engine)


def _cast(char, skill_id, game=None):
    """Queues + resolves one skill for p1 with exactly the dice it costs."""
    if game is None:
        team = [copy.deepcopy(char), dict(copy.deepcopy(char), id='ally_2')]
        dummy = dict(copy.deepcopy(char), id='dummy', health=999, maxHealth=999)
        game = {'turn': 'p1', 'winner': None, 'turn_count': 3, 'pending_moves': [],
                'players': {'p1': {'id': 'a', 'resources': [], 'status': [], 'team': team},
                            'p2': {'id': 'b', 'resources': [], 'status': [], 'team': [dummy]}}}
    actor = game['players']['p1']['team'][0]
    skill = next(s for s in actor['skills'] if s['id'] == skill_id)
    skill['locked'] = False
    skill['currentCooldown'] = 0
    game['turn'] = 'p1'
    game['pending_moves'] = []
    pay = [t for t, n in skill['cost'].items() if t != 'random' for _ in range(n)] + ['rage'] * skill['cost'].get('random', 0)
    game['players']['p1']['resources'] = list(pay)
    side = 'p2' if skill['target_type'] in ('enemy', 'enemy_team') else 'p1'
    ge.queue_move(game, 'p1', actor['id'], skill_id, side, 0)
    ge.resolve_turn(game, pay)
    return game


def test_every_skill_can_be_cast():
    """Every skill in the roster (and every primed version) runs through the
    real engine once without crashing -- catches content the models accept
    but the engine can't execute (e.g. the old Kaioken NameError)."""
    catalog = cl.load_catalog()
    bad = []
    for cid, char in catalog.items():
        for skill in char['skills']:
            try:
                game = _cast(char, skill['id'])
                for e in skill['effects']:
                    if e['type'] == 'prime_skill':  # also cast the swapped-in version
                        _cast(char, e['skill_id'], game)
            except Exception as e:
                bad.append(f"{cid}.{skill['id']}: {type(e).__name__}: {e}")
    check(f"all {sum(len(c['skills']) for c in catalog.values())} skills (+ primed versions) cast without errors",
          bad == [], bad)


# --- invalid content is rejected with useful messages -------------------------

def test_valid_minimal_character_loads():
    catalog, problems = load([dict(valid_char(), notes='design note')])
    check("a minimal valid character loads", problems == [] and 'test_char' in catalog, problems)
    skills = catalog['test_char']['skills'] if catalog else []
    check("a shared skill reference resolves with its override applied",
          len(skills) == 2 and skills[1]['name'] == 'Block' and skills[1]['effects'][0]['type'] == 'invulnerable')


def test_malformed_files():
    rejected("malformed JSON reports the line and column", [], "invalid JSON at line",
             raw_files={'broken.json': '{"id": "broken", "name": '})
    rejected("an empty characters folder is an error", [], "no character files found")
    rejected("a missing shared_abilities.json is reported", [valid_char()], "can't read file", shared=None)


def test_shape_errors():
    rejected("unknown effect type", [with_effect({'type': 'damge', 'value': 10})], "does not match any of the expected tags")
    rejected("typo'd field name", [with_effect({'type': 'damage', 'vlaue': 10})], "Extra inputs are not permitted")
    rejected("missing required field", [with_effect({'type': 'damage'})], "Field required")
    rejected("unknown Ki type in cost", [with_skill(cost={'fire': 1})], "Extra inputs are not permitted")
    rejected("zero cost amount", [with_skill(cost={'energy': 0})], "greater than or equal to 1")
    rejected("invalid target_type", [with_skill(target_type='enemies')], "Input should be")
    rejected("wrong value type", [with_effect({'type': 'damage', 'value': 'ten'})], "valid integer")
    rejected("uppercase / spaced id", [dict(valid_char(), id='Bad Id')], "should match pattern")
    rejected("unknown skill class", [with_skill(classes=['magic'])], "Input should be")
    rejected("a field that only exists on another effect type",
             [with_effect({'type': 'damage', 'value': 5, 'description_template': '{value}'})],
             "Extra inputs are not permitted")


def test_boundaries():
    for hp, ok in ((0, False), (1, True), (999, True), (1000, False)):
        _, problems = load([dict(valid_char(), health=hp)])
        check(f"health {hp} is {'accepted' if ok else 'rejected'}", (problems == []) == ok, problems)
    for d, ok in ((0, False), (1, True), (20, True), (21, False)):
        _, problems = load([with_effect({'type': 'stun', 'duration': d})])
        check(f"duration {d} is {'accepted' if ok else 'rejected'}", (problems == []) == ok, problems)
    for cd, ok in ((-1, False), (0, True), (20, True), (21, False)):
        _, problems = load([with_skill(cooldown=cd)])
        check(f"cooldown {cd} is {'accepted' if ok else 'rejected'}", (problems == []) == ok, problems)
    _, problems = load([with_effect({'type': 'damage_taken_mod', 'value': -0.25, 'duration': 2})])
    check("a negative percent modifier (-25%) is accepted", problems == [], problems)


def test_cross_reference_errors():
    rejected("missing character image", [dict(valid_char(), image='characters/nope.png')], "image not found")
    rejected("missing skill image", [with_skill(image='nope.png')], "image not found")
    rejected("unknown shared ability", [dict(valid_char(), skills=[valid_char()['skills'][0], {'use': 'nope'}])],
             "unknown shared ability")
    rejected("a shared-skill reference can't change mechanics",
             [dict(valid_char(), skills=[valid_char()['skills'][0], {'use': 'afterimage_technique', 'cooldown': 0}])],
             "Extra inputs are not permitted")
    rejected("the universal skill is required", [dict(valid_char(), skills=[valid_char()['skills'][0]])],
             "exactly once (found 0)")
    rejected("duplicate skill id in a kit",
             [dict(valid_char(), skills=[valid_char()['skills'][0]] * 2 + [{'use': 'afterimage_technique'}])],
             "duplicate skill id")
    rejected("file name must match the id", [], "file name must be",
             raw_files={'wrong_name.json': json.dumps(valid_char('right_name'))})
    rejected("skill_id must exist in the kit",
             [with_effect({'type': 'unlock_skill_on_stack', 'stack_key': 'k', 'at_stack': 1, 'skill_id': 'ghost'})],
             "is not in this kit")
    stack = {'type': 'add_stack', 'stack_key': 'k'}
    rejected("effect_index must be in range",
             [with_skill(effects=[stack, {'type': 'boost_skill_on_stack', 'stack_key': 'k', 'at_stack': 1,
                                          'skill_id': 'hit', 'effect_index': 5, 'bonus': 1}])], "out of range")
    rejected("stack_key must be added somewhere in the kit",
             [with_effect({'type': 'self_damage_by_stack', 'stack_key': 'never', 'schedule': [5]})],
             "never added by an add_stack")
    rejected("description_template may only use {value}",
             [with_skill(effects=[stack, {'type': 'scale_skill_by_stack', 'stack_key': 'k', 'skill_id': 'hit',
                                          'base': 1, 'increment': 1, 'description_template': '{damage} Dmg'}])],
             "must only use {value}")
    rejected("unprime mark must match a prime mark",
             [with_effect({'type': 'unprime_skill', 'skill_id': 'hit', 'mark': 'nope'})], "doesn't match any prime_skill")
    rejected("a locked skill must be unlockable", [with_skill(locked=True)], "nothing in the kit unlocks it")


def test_all_problems_reported_together():
    _, problems = load([dict(valid_char('a_one'), image='characters/nope.png'),
                        dict(with_skill(cooldown=-1), id='b_two')])
    check("problems from several files are reported in one error", len(problems) >= 2, problems)
    check("each problem names its file", all(p.startswith('content/') for p in problems), problems)


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_')]

if __name__ == '__main__':
    for t in TESTS:
        print(f"{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print(f"All {len(TESTS)} test functions passed.")
