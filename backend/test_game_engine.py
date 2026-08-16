"""
Direct unit tests for the effect engine (game_engine.py), bypassing
Flask/Socket.IO entirely. Run with:  python test_game_engine.py

These build minimal in-memory game states and call the engine functions
the same way app.py does, so they exercise real resolution order (damage
mitigation, invulnerability, reactive defenses, chakra pool effects, etc.)
without needing a live server or a browser.
"""
import copy
import game_engine as ge

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


def make_char(cid, health=100, defense=0):
    return {
        "id": cid, "name": cid, "image": f"{cid}.png",
        "health": health, "maxHealth": 100, "defense": defense, "status": [],
        "skills": []
    }


def make_game():
    """Two players, one character each, empty resource pools, p1's turn."""
    return {
        'roomId': 'test', 'turn': 'p1', 'winner': None, 'turn_count': 1,
        'players': {
            'p1': {'id': 'sid1', 'resources': [], 'status': [], 'team': [make_char('A')]},
            'p2': {'id': 'sid2', 'resources': [], 'status': [], 'team': [make_char('B')]},
        },
        'pending_moves': []
    }


def run_skill_via_queue(game, skill, target_index=0, target_role='p2'):
    """Attach `skill` to p1's character A, queue it, resolve with empty payment
    (assumes the skill's cost is empty for these unit tests)."""
    actor = game['players']['p1']['team'][0]
    actor['skills'] = [skill]
    for s in actor['skills']:
        s.setdefault('currentCooldown', 0)
    ge.queue_move(game, 'p1', 'A', skill['id'], target_role, target_index)
    return ge.resolve_turn(game, [])


# ---------------------------------------------------------------------------

def test_basic_damage():
    game = make_game()
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    b = game['players']['p2']['team'][0]
    check("basic damage reduces HP by 20", b['health'] == 80, b['health'])


def test_defense_absorbs_then_hp():
    game = make_game()
    game['players']['p2']['team'][0]['defense'] = 15
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    b = game['players']['p2']['team'][0]
    check("defense absorbs 15, remaining 5 hits HP", b['defense'] == 0 and b['health'] == 95,
          (b['defense'], b['health']))


def test_piercing_ignores_reduction_not_defense():
    game = make_game()
    b = game['players']['p2']['team'][0]
    b['defense'] = 5
    ge.add_status(b, {'type': 'damage_taken_mod', 'value': -0.5, 'duration': 10, 'tag': 'buff'})
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "piercing_damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    # 20 dmg, reduction ignored -> 20, defense absorbs 5 -> 15 to HP
    check("piercing ignores damage reduction but still hits defense first",
          b['defense'] == 0 and b['health'] == 85, (b['defense'], b['health']))


def test_affliction_ignores_everything():
    game = make_game()
    b = game['players']['p2']['team'][0]
    b['defense'] = 50
    ge.add_status(b, {'type': 'invulnerable', 'duration': 10, 'tag': 'buff'})
    ge.add_status(b, {'type': 'damage_taken_mod', 'value': -1.0, 'duration': 10, 'tag': 'buff'})
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "affliction_damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    check("affliction bypasses invuln, defense, and damage reduction", b['health'] == 80, b['health'])


def test_general_invulnerability_blocks_damage():
    game = make_game()
    b = game['players']['p2']['team'][0]
    ge.add_status(b, {'type': 'invulnerable', 'duration': 10, 'tag': 'buff'})
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    check("invulnerable target takes no damage", b['health'] == 100, b['health'])


def test_class_specific_invulnerability():
    game = make_game()
    b = game['players']['p2']['team'][0]
    ge.add_status(b, {'type': 'physical_invulnerable', 'duration': 10, 'tag': 'buff'})
    physical_skill = {"id": "s1", "name": "s1", "cost": {}, "target_type": "enemy", "classes": ["physical"],
                       "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, physical_skill)
    check("physical_invulnerable blocks a physical-classed skill", b['health'] == 100, b['health'])

    chakra_skill = {"id": "s2", "name": "s2", "cost": {}, "target_type": "enemy", "classes": ["chakra"],
                     "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    game['turn'] = 'p1'
    run_skill_via_queue(game, chakra_skill)
    check("physical_invulnerable does NOT block a chakra-classed skill", b['health'] == 80, b['health'])


def test_dot_ticks_and_expires():
    game = make_game()
    a = game['players']['p1']['team'][0]
    ge.add_status(a, {'type': 'dot', 'value': 10, 'duration': 2, 'tag': 'harmful'})  # 1 round
    ge.start_turn(game, 'p2')  # tick 1 (duration 2 -> 1): should apply dmg, stay active
    check("dot ticks damage on turn start", a['health'] == 90, a['health'])
    ge.start_turn(game, 'p1')  # tick 2 (duration 1 -> 0): applies again, then expires
    check("dot ticks again then expires", a['health'] == 80 and a.get('status') == [], (a['health'], a['status']))


def test_hot_ticks():
    game = make_game()
    a = game['players']['p1']['team'][0]
    a['health'] = 50
    ge.add_status(a, {'type': 'hot', 'value': 10, 'duration': 2, 'tag': 'buff'})
    ge.start_turn(game, 'p2')
    check("hot heals on tick", a['health'] == 60, a['health'])


def test_heal_block_prevents_healing():
    game = make_game()
    b = game['players']['p2']['team'][0]
    b['health'] = 50
    ge.add_status(b, {'type': 'heal_block', 'duration': 10, 'tag': 'harmful'})
    ge.apply_heal(b, 30)
    check("heal_block prevents healing", b['health'] == 50, b['health'])


def test_stun_blocks_queue():
    game = make_game()
    a = game['players']['p1']['team'][0]
    a['skills'] = [{"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
                     "effects": [{"type": "damage", "value": 5}], "cooldown": 0, "currentCooldown": 0}]
    ge.add_status(a, {'type': 'stun', 'duration': 10, 'tag': 'harmful'})
    try:
        ge.queue_move(game, 'p1', 'A', 's', 'p2', 0)
        check("stunned character cannot queue a move", False, "no exception raised")
    except Exception as e:
        check("stunned character cannot queue a move", "stunned" in str(e).lower(), str(e))


def test_silence_blocks_matching_class_only():
    game = make_game()
    a = game['players']['p1']['team'][0]
    a['skills'] = [
        {"id": "phys", "name": "phys", "cost": {}, "target_type": "enemy", "classes": ["physical"],
         "effects": [{"type": "damage", "value": 5}], "cooldown": 0, "currentCooldown": 0},
        {"id": "chak", "name": "chak", "cost": {}, "target_type": "enemy", "classes": ["chakra"],
         "effects": [{"type": "damage", "value": 5}], "cooldown": 0, "currentCooldown": 0},
    ]
    ge.add_status(a, {'type': 'silence', 'classes': ['chakra'], 'duration': 10, 'tag': 'harmful'})
    blocked = False
    try:
        ge.queue_move(game, 'p1', 'A', 'chak', 'p2', 0)
    except Exception:
        blocked = True
    check("silence blocks the matching class", blocked)

    allowed = True
    try:
        ge.queue_move(game, 'p1', 'A', 'phys', 'p2', 0)
    except Exception:
        allowed = False
    check("silence does not block a different class", allowed)


def test_chakra_restrict_blocks_cost():
    game = make_game()
    a = game['players']['p1']['team'][0]
    a['skills'] = [{"id": "s", "name": "s", "cost": {"energy": 1}, "target_type": "enemy",
                     "effects": [{"type": "damage", "value": 5}], "cooldown": 0, "currentCooldown": 0}]
    ge.add_status(game['players']['p1'], {'type': 'chakra_restrict', 'chakra_type': 'energy',
                                            'duration': 10, 'tag': 'harmful'})
    blocked = False
    try:
        ge.queue_move(game, 'p1', 'A', 's', 'p2', 0)
    except Exception:
        blocked = True
    check("chakra_restrict blocks queueing a move needing that chakra type", blocked)


def test_remove_and_steal_and_regen_chakra():
    # NOTE: these call apply_effect directly rather than going through
    # queue_move/resolve_turn, because resolve_turn hands the turn to the
    # next player via start_turn(), which itself rolls a fresh die for
    # them -- that's correct game behavior, but it would contaminate a
    # pool-contents assertion taken right after the effect.
    game = make_game()
    game['players']['p2']['resources'] = ['energy', 'martial', 'rage']
    ge.apply_effect({'type': 'remove_chakra', 'amount': 1, 'chakra_type': 'energy'},
                     actor=game['players']['p1']['team'][0], targets=[],
                     player=game['players']['p1'], opponent=game['players']['p2'], skill_classes=[])
    check("remove_chakra removes the specific type from opponent",
          game['players']['p2']['resources'] == ['martial', 'rage'], game['players']['p2']['resources'])

    game2 = make_game()
    game2['players']['p2']['resources'] = ['martial']
    game2['players']['p1']['resources'] = []
    ge.apply_effect({'type': 'steal_chakra', 'amount': 1},
                     actor=game2['players']['p1']['team'][0], targets=[],
                     player=game2['players']['p1'], opponent=game2['players']['p2'], skill_classes=[])
    check("steal_chakra moves a die from opponent to caster",
          game2['players']['p2']['resources'] == [] and game2['players']['p1']['resources'] == ['martial'],
          (game2['players']['p1']['resources'], game2['players']['p2']['resources']))

    game3 = make_game()
    ge.apply_effect({'type': 'chakra_regen', 'amount': 2},
                     actor=game3['players']['p1']['team'][0], targets=[],
                     player=game3['players']['p1'], opponent=game3['players']['p2'], skill_classes=[])
    check("chakra_regen adds dice to caster's own pool", len(game3['players']['p1']['resources']) == 2,
          game3['players']['p1']['resources'])


def test_chakra_drain_over_time():
    # Uses tick_statuses() directly rather than start_turn(), for the same
    # reason as above -- start_turn also rolls a fresh die for the player
    # whose turn is beginning, which would confound the pool-size assertion.
    game = make_game()
    game['players']['p2']['resources'] = ['energy', 'martial', 'rage']
    ge.add_status(game['players']['p2'], {'type': 'chakra_drain_over_time', 'value': 1, 'duration': 2, 'tag': 'harmful'})
    ge.tick_statuses(game)
    check("chakra_drain_over_time removes dice on tick", len(game['players']['p2']['resources']) == 2,
          game['players']['p2']['resources'])


def test_cleanse_removes_harmful():
    game = make_game()
    a = game['players']['p1']['team'][0]
    ge.add_status(a, {'type': 'stun', 'duration': 10, 'tag': 'harmful'})
    ge.add_status(a, {'type': 'hot', 'value': 5, 'duration': 10, 'tag': 'buff'})
    ge.apply_effect({'type': 'cleanse', 'scope': 'harmful'}, actor=a, targets=[a],
                     player=game['players']['p1'], opponent=game['players']['p2'], skill_classes=[])
    types_left = [s['type'] for s in a['status']]
    check("cleanse strips harmful but keeps buffs", types_left == ['hot'], types_left)


def test_damage_mods_stack_multiplicatively_as_additive_percent():
    game = make_game()
    a = game['players']['p1']['team'][0]
    b = game['players']['p2']['team'][0]
    ge.add_status(a, {'type': 'damage_dealt_mod', 'value': 0.5, 'duration': 10, 'tag': 'buff'})   # +50% dealt
    ge.add_status(b, {'type': 'damage_taken_mod', 'value': 0.25, 'duration': 10, 'tag': 'harmful'})  # +25% taken
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    # 20 * 1.5 * 1.25 = 37.5 -> round to 38 (banker's rounding on .5 -> round(37.5)=38 in Py3 round-half-even? check)
    expected = round(20 * 1.5 * 1.25)
    check("damage buffs/debuffs apply multiplicatively", b['health'] == 100 - expected,
          (b['health'], expected))


def test_dodge_negates_next_harmful_effect_once():
    game = make_game()
    b = game['players']['p2']['team'][0]
    ge.add_status(b, {'type': 'dodge', 'duration': 10, 'tag': 'buff'})
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    check("dodge negates the first hit", b['health'] == 100, b['health'])
    game['turn'] = 'p1'
    skill2 = {"id": "s2", "name": "s2", "cost": {}, "target_type": "enemy",
              "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill2)
    check("dodge is consumed, second hit lands", b['health'] == 80, b['health'])


def test_counter_negates_damage():
    game = make_game()
    b = game['players']['p2']['team'][0]
    ge.add_status(b, {'type': 'counter', 'duration': 10, 'tag': 'buff'})
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    check("counter fully negates damage", b['health'] == 100, b['health'])


def test_reflect_sends_damage_back():
    game = make_game()
    a = game['players']['p1']['team'][0]
    b = game['players']['p2']['team'][0]
    ge.add_status(b, {'type': 'reflect', 'duration': 10, 'tag': 'buff'})
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    check("reflect leaves target unharmed and hits the attacker instead",
          b['health'] == 100 and a['health'] == 80, (b['health'], a['health']))


def test_team_targeting():
    game = make_game()
    game['players']['p2']['team'].append(make_char('C'))
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy_team",
             "effects": [{"type": "damage", "value": 10}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    healths = [c['health'] for c in game['players']['p2']['team']]
    check("enemy_team targeting hits every living enemy", healths == [90, 90], healths)


def test_cannot_heal_dead():
    game = make_game()
    b = game['players']['p2']['team'][0]
    b['health'] = 0
    ge.apply_heal(b, 50)
    check("dead characters cannot be healed", b['health'] == 0, b['health'])


def test_legacy_aoe_damage_still_works():
    game = make_game()
    game['players']['p2']['team'].append(make_char('C'))
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "aoe_damage", "value": 10}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    healths = [c['health'] for c in game['players']['p2']['team']]
    check("legacy aoe_damage still hits the whole opponent team", healths == [90, 90], healths)


def test_win_condition_still_works():
    game = make_game()
    b = game['players']['p2']['team'][0]
    b['health'] = 5
    skill = {"id": "s", "name": "s", "cost": {}, "target_type": "enemy",
             "effects": [{"type": "damage", "value": 20}], "cooldown": 0}
    run_skill_via_queue(game, skill)
    check("winner is set once a whole team is dead", game.get('winner') == 'p1', game.get('winner'))


def test_content_smoke():
    """Load the real character roster and make sure every skill's effects
    reference known effect types (catches typos in characters.py)."""
    import characters
    known_types = {
        'damage', 'piercing_damage', 'affliction_damage', 'self_damage', 'aoe_damage', 'dot',
        'heal', 'hot', 'team_heal', 'heal_block', 'stun', 'silence', 'defense', 'remove_defense',
        'damage_taken_mod', 'damage_dealt_mod', 'heal_received_mod', 'heal_dealt_mod',
        'invulnerable', 'physical_invulnerable', 'chakra_invulnerable', 'mental_invulnerable',
        'dodge', 'counter', 'reflect', 'cleanse',
        'remove_chakra', 'steal_chakra', 'chakra_regen', 'chakra_restrict', 'chakra_drain_over_time',
    }
    bad = []
    for cid, char in characters.CHARACTERS.items():
        for skill in char['skills']:
            for effect in skill.get('effects', []):
                if effect['type'] not in known_types:
                    bad.append((cid, skill['id'], effect['type']))
    check("every skill effect type in characters.py is recognized by the engine", bad == [], bad)


def test_goku_saiyan_saga_kit():
    """Exercises Goku's real kit straight from characters.py (not synthetic
    skills), so a future balance tweak that breaks the intended interactions
    (e.g. Kaioken no longer buffing Kaioken Attack) gets caught."""
    import characters
    skills_by_id = {s['id']: s for s in characters.CHARACTERS['goku_saiyan_saga']['skills']}
    check("goku_saiyan_saga has the 3 signature skills + the universal one",
          set(skills_by_id) == {'kamehameha', 'kaioken', 'kaioken_attack', 'afterimage_technique'},
          set(skills_by_id))

    # Kamehameha: damage + stun
    game = make_game()
    a = game['players']['p1']['team'][0]
    a['skills'] = [copy.deepcopy(skills_by_id['kamehameha'])]
    a['skills'][0]['currentCooldown'] = 0
    ge.queue_move(game, 'p1', 'A', 'kamehameha', 'p2', 0)
    ge.resolve_turn(game, [])
    b = game['players']['p2']['team'][0]
    check("Kamehameha damages and stuns the target",
          b['health'] < 100 and any(s['type'] == 'stun' for s in b['status']), (b['health'], b['status']))

    # Kaioken: costs the caster HP and grants a self damage buff that should
    # then boost Kaioken Attack's damage on a later use.
    game2 = make_game()
    a2 = game2['players']['p1']['team'][0]
    b2 = game2['players']['p2']['team'][0]
    a2['skills'] = [copy.deepcopy(skills_by_id['kaioken']), copy.deepcopy(skills_by_id['kaioken_attack'])]
    for s in a2['skills']: s['currentCooldown'] = 0
    hp_before = a2['health']

    ge.queue_move(game2, 'p1', 'A', 'kaioken', 'p1', 0)
    ge.resolve_turn(game2, [])
    check("Kaioken costs the caster HP (bodily strain)", a2['health'] < hp_before, a2['health'])
    check("Kaioken grants a self damage_dealt_mod buff",
          any(s['type'] == 'damage_dealt_mod' for s in a2['status']), a2['status'])

    game2['turn'] = 'p1'  # same player follows up immediately, to isolate the buff interaction
    ge.queue_move(game2, 'p1', 'A', 'kaioken_attack', 'p2', 0)
    ge.resolve_turn(game2, [])
    base_value = skills_by_id['kaioken_attack']['effects'][0]['value']
    buff_value = skills_by_id['kaioken']['effects'][0]['value']
    expected_dmg = round(base_value * (1 + buff_value))
    check("Kaioken Attack deals boosted damage while Kaioken is active",
          b2['health'] == 100 - expected_dmg, (b2['health'], expected_dmg))

    # Afterimage Technique: blocks the very next incoming attack
    game3 = make_game()
    a3 = game3['players']['p1']['team'][0]
    b3 = game3['players']['p2']['team'][0]
    a3['skills'] = [copy.deepcopy(skills_by_id['afterimage_technique'])]
    a3['skills'][0]['currentCooldown'] = 0
    ge.queue_move(game3, 'p1', 'A', 'afterimage_technique', 'p1', 0)
    ge.resolve_turn(game3, [])
    check("Afterimage Technique grants self-invulnerability",
          any(s['type'] == 'invulnerable' for s in a3['status']), a3['status'])

    game3['turn'] = 'p2'
    b3['skills'] = [{'id': 'poke', 'name': 'poke', 'cost': {}, 'target_type': 'enemy',
                      'effects': [{'type': 'damage', 'value': 20}], 'cooldown': 0, 'currentCooldown': 0}]
    ge.queue_move(game3, 'p2', 'B', 'poke', 'p1', 0)
    ge.resolve_turn(game3, [])
    check("Afterimage Technique blocks the incoming attack", a3['health'] == 100, a3['health'])


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_')]

if __name__ == '__main__':
    for t in TESTS:
        print(f"{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    else:
        print(f"All {len(TESTS)} test functions passed.")
