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


def dice_for_cost(cost):
    """Exactly the dice that pay `cost` (random requirements paid with energy)."""
    return [t for t, amt in cost.items() if t != 'random' for _ in range(amt)] + ['energy'] * cost.get('random', 0)


def play(game, player_id, char_id, skill_id, target_role, target_index):
    """Queue + resolve one real (costed) skill the legitimate way: hand the
    player exactly the dice it costs, then pay with them."""
    char = next(c for c in game['players'][player_id]['team'] if c['id'] == char_id)
    skill = next(s for s in char['skills'] if s['id'] == skill_id)
    payment = dice_for_cost(skill['cost'])
    game['players'][player_id]['resources'].extend(payment)
    ge.queue_move(game, player_id, char_id, skill_id, target_role, target_index)
    return ge.resolve_turn(game, payment)


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
    game['players']['p1']['resources'] = ['energy']  # affordable, so only the restriction can block it
    blocked_msg = ''
    try:
        ge.queue_move(game, 'p1', 'A', 's', 'p2', 0)
    except Exception as e:
        blocked_msg = str(e)
    check("chakra_restrict blocks queueing a move needing that chakra type",
          'restricted' in blocked_msg.lower(), blocked_msg)


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


def test_protect_redirects_damage_to_protector():
    game = make_game()
    game['players']['p1']['team'].append(make_char('Guardian'))
    protector = game['players']['p1']['team'][1]
    protected = game['players']['p1']['team'][0]
    enemy = game['players']['p2']['team'][0]

    ge.apply_effect({'type': 'protect', 'duration': 1}, actor=protector, targets=[protected],
                     player=game['players']['p1'], opponent=game['players']['p2'], skill_classes=[])
    check("protect grants the target a 'protected' status",
          any(s['type'] == 'protected' for s in protected['status']), protected['status'])

    ge.apply_effect({'type': 'damage', 'value': 20}, actor=enemy, targets=[protected],
                     player=game['players']['p2'], opponent=game['players']['p1'], skill_classes=[])
    check("the protected ally takes no damage", protected['health'] == 100, protected['health'])
    check("the protector takes the damage instead", protector['health'] == 80, protector['health'])
    check("protection is consumed after one hit",
          not any(s['type'] == 'protected' for s in protected['status']), protected['status'])

    # A second hit with no protection left should land on the original target again
    ge.apply_effect({'type': 'damage', 'value': 15}, actor=enemy, targets=[protected],
                     player=game['players']['p2'], opponent=game['players']['p1'], skill_classes=[])
    check("further hits land normally once protection is used up", protected['health'] == 85, protected['health'])


def test_delayed_damage_charges_then_detonates_next_turn():
    game = make_game()
    a = game['players']['p1']['team'][0]
    b = game['players']['p2']['team'][0]
    ge.add_status(b, {'type': 'invulnerable', 'duration': 10, 'tag': 'buff'})

    ge.apply_effect({'type': 'delayed_damage', 'value': 40, 'duration': 1}, actor=a, targets=[b],
                     player=game['players']['p1'], opponent=game['players']['p2'], skill_classes=[])
    check("delayed_damage deals no damage immediately", b['health'] == 100, b['health'])
    check("the charging status is visible on the target",
          any(s['type'] == 'delayed_damage' for s in b['status']), b['status'])

    ge.start_turn(game, 'p2')  # opponent's turn: 1st tick, not detonated yet
    check("still no damage after the opponent's turn (1 tick in)", b['health'] == 100, b['health'])

    ge.start_turn(game, 'p1')  # caster's own next turn: 2nd tick, detonates now
    check("detonates for the full 40 at the start of the caster's next turn",
          b['health'] == 60, b['health'])
    check("detonation ignores invulnerability", True)  # target had 'invulnerable' the whole time
    check("the charging status is gone after detonating",
          not any(s['type'] == 'delayed_damage' for s in b['status']), b['status'])


def test_random_multi_damage_hits_exactly_n_targets():
    game = make_game()
    game['players']['p2']['team'].append(make_char('C'))
    game['players']['p2']['team'].append(make_char('D'))
    a = game['players']['p1']['team'][0]

    ge.apply_effect({'type': 'random_multi_damage', 'value': 25, 'count': 2}, actor=a, targets=[],
                     player=game['players']['p1'], opponent=game['players']['p2'], skill_classes=[])
    healths = [c['health'] for c in game['players']['p2']['team']]
    hit_count = sum(1 for h in healths if h == 75)
    untouched_count = sum(1 for h in healths if h == 100)
    check("random_multi_damage hits exactly 2 of the 3 enemies for the full value",
          hit_count == 2 and untouched_count == 1, healths)


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
        'add_stack', 'self_damage_by_stack', 'boost_skill_on_stack',
        'unlock_skill_on_stack', 'scale_skill_by_stack', 'set_skill_cost_on_stack',
        'protect', 'random_multi_damage', 'delayed_damage',
        'prime_skill', 'unprime_skill',
        'damage_ignore_invuln', 'expiring_defense', 'mark_for_counter',
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
    gets caught. Kaioken is a permanent, repeatable, escalating transform
    (not a temporary buff) that rewrites Kamehameha and Kaioken Attack in
    place -- this is the main thing worth regression-testing here."""
    import characters
    if 'goku_saiyan_saga' not in characters.CHARACTERS:
        print("  SKIPPED: goku_saiyan_saga not in the current roster")
        return
    skills_by_id = {s['id']: s for s in characters.CHARACTERS['goku_saiyan_saga']['skills']}
    check("goku_saiyan_saga has the 3 signature skills + the universal one",
          set(skills_by_id) == {'kamehameha', 'kaioken', 'kaioken_attack', 'afterimage_technique'},
          set(skills_by_id))
    check("Kaioken Attack starts locked in its definition", skills_by_id['kaioken_attack'].get('locked') is True)

    game = make_game()
    a = game['players']['p1']['team'][0]
    b = game['players']['p2']['team'][0]
    a['skills'] = [copy.deepcopy(skills_by_id['kamehameha']),
                   copy.deepcopy(skills_by_id['kaioken']),
                   copy.deepcopy(skills_by_id['kaioken_attack'])]
    for s in a['skills']: s['currentCooldown'] = 0
    kamehameha_live = next(s for s in a['skills'] if s['id'] == 'kamehameha')
    kaioken_live = next(s for s in a['skills'] if s['id'] == 'kaioken')
    kaioken_attack_live = next(s for s in a['skills'] if s['id'] == 'kaioken_attack')

    # Kamehameha at base power, before any Kaioken use
    play(game, 'p1', 'A', 'kamehameha', 'p2', 0)
    check("Kamehameha deals its rounded base damage (25) before Kaioken", b['health'] == 75, b['health'])
    check("Kamehameha is pure damage, no stun", b['status'] == [], b['status'])

    # Kaioken Attack is locked before Kaioken has ever been used
    game['turn'] = 'p1'
    kamehameha_live['currentCooldown'] = 0
    blocked_msg = None
    try:
        ge.queue_move(game, 'p1', 'A', 'kaioken_attack', 'p2', 0)
    except Exception as e:
        blocked_msg = str(e)
    check("Kaioken Attack cannot be queued before Kaioken is used", blocked_msg is not None)
    check("locked-skill error uses the authored reason",
          blocked_msg == skills_by_id['kaioken_attack']['locked_reason'], blocked_msg)

    # --- 1st Kaioken use ---
    check("Kaioken's cost before any use is 1 Random", kaioken_live['cost'] == {'random': 1}, kaioken_live['cost'])
    hp_before = a['health']
    play(game, 'p1', 'A', 'kaioken', 'p1', 0)
    check("1st Kaioken use costs 20 HP", a['health'] == hp_before - 20, a['health'])
    check("1st Kaioken use sets the stack counter to 1", a.get('stacks', {}).get('kaioken') == 1, a.get('stacks'))
    check("Kaioken's cost permanently becomes 2 Random after the 1st use",
          kaioken_live['cost'] == {'random': 2}, kaioken_live['cost'])
    check("Kamehameha is permanently boosted +20 after the 1st Kaioken use (25 -> 45)",
          kamehameha_live['effects'][0]['value'] == 45, kamehameha_live['effects'][0]['value'])
    check("Kaioken Attack is unlocked after the 1st Kaioken use", kaioken_attack_live.get('locked') is False)
    check("Kaioken Attack's damage is set to its base (40) on the 1st Kaioken use",
          kaioken_attack_live['effects'][0]['value'] == 40, kaioken_attack_live['effects'][0]['value'])

    # Kamehameha now actually hits harder in combat
    game['turn'] = 'p1'
    kamehameha_live['currentCooldown'] = 0
    hp_before_b = b['health']
    play(game, 'p1', 'A', 'kamehameha', 'p2', 0)
    check("Kamehameha's boosted damage actually applies in combat", b['health'] == hp_before_b - 45, b['health'])

    # --- 2nd Kaioken use: still 20 HP, Kaioken Attack scales to 50, Kamehameha does NOT re-boost ---
    game['turn'] = 'p1'
    kaioken_live['currentCooldown'] = 0
    hp_before2 = a['health']
    play(game, 'p1', 'A', 'kaioken', 'p1', 0)
    check("2nd Kaioken use still costs 20 HP", a['health'] == hp_before2 - 20, a['health'])
    check("Kaioken's cost stays at 2 Random (doesn't escalate further)",
          kaioken_live['cost'] == {'random': 2}, kaioken_live['cost'])
    check("Kamehameha's boost does not stack further on the 2nd use",
          kamehameha_live['effects'][0]['value'] == 45, kamehameha_live['effects'][0]['value'])
    check("Kaioken Attack scales to 50 on the 2nd Kaioken use",
          kaioken_attack_live['effects'][0]['value'] == 50, kaioken_attack_live['effects'][0]['value'])

    # --- 3rd Kaioken use: cost jumps to 40 HP, Kaioken Attack scales to 60 ---
    game['turn'] = 'p1'
    kaioken_live['currentCooldown'] = 0
    hp_before3 = a['health']
    play(game, 'p1', 'A', 'kaioken', 'p1', 0)
    check("3rd Kaioken use costs 40 HP", a['health'] == hp_before3 - 40, a['health'])
    check("Kaioken Attack scales to 60 on the 3rd Kaioken use",
          kaioken_attack_live['effects'][0]['value'] == 60, kaioken_attack_live['effects'][0]['value'])

    # Afterimage Technique: blocks the very next incoming attack
    game2 = make_game()
    a2 = game2['players']['p1']['team'][0]
    b2 = game2['players']['p2']['team'][0]
    a2['skills'] = [copy.deepcopy(skills_by_id['afterimage_technique'])]
    a2['skills'][0]['currentCooldown'] = 0
    play(game2, 'p1', 'A', 'afterimage_technique', 'p1', 0)
    check("Afterimage Technique grants self-invulnerability",
          any(s['type'] == 'invulnerable' for s in a2['status']), a2['status'])

    game2['turn'] = 'p2'
    b2['skills'] = [{'id': 'poke', 'name': 'poke', 'cost': {}, 'target_type': 'enemy',
                      'effects': [{'type': 'damage', 'value': 20}], 'cooldown': 0, 'currentCooldown': 0}]
    play(game2, 'p2', 'B', 'poke', 'p1', 0)
    check("Afterimage Technique blocks the incoming attack", a2['health'] == 100, a2['health'])


def test_tien_best_friend_primes_tri_beam():
    """Best Friend temporarily swaps Tri-Beam's cost/effects to a stronger
    version -- unlike Kaioken's permanent transform, this must revert, either
    when Tri-Beam actually gets used (consumed) or when the priming window
    runs out unused (expired). Both paths are tested against Tien's real
    data from characters.py."""
    import characters
    if 'tien_saiyan_saga' not in characters.CHARACTERS:
        print("  SKIPPED: tien_saiyan_saga not in the current roster")
        return
    skills_by_id = {s['id']: s for s in characters.CHARACTERS['tien_saiyan_saga']['skills']}
    base_tri_beam_cost = dict(skills_by_id['tri_beam']['cost'])
    base_tri_beam_effects = copy.deepcopy(skills_by_id['tri_beam']['effects'])

    # --- Path 1: primed, then actually used (consumed) ---
    # (affliction_damage's own "ignores invulnerability" behavior is already
    # covered generically by test_affliction_ignores_everything -- no need
    # to duplicate that here, and doing so would incorrectly also block
    # Best Friend's plain stun, which unlike affliction is NOT invuln-exempt.)
    game = make_game()
    a = game['players']['p1']['team'][0]
    b = game['players']['p2']['team'][0]
    a['skills'] = [copy.deepcopy(skills_by_id['best_friend']), copy.deepcopy(skills_by_id['tri_beam'])]
    for s in a['skills']: s['currentCooldown'] = 0
    tri_beam_live = next(s for s in a['skills'] if s['id'] == 'tri_beam')

    check("Tri-Beam starts with its base cost", tri_beam_live['cost'] == base_tri_beam_cost, tri_beam_live['cost'])

    play(game, 'p1', 'A', 'best_friend', 'p1', 0)  # target_type is "self" -- no enemy effect anymore
    check("Best Friend primes Tri-Beam's cost to 2 Random",
          tri_beam_live['cost'] == {'random': 2}, tri_beam_live['cost'])
    check("Best Friend primes Tri-Beam's effects (affliction+stun+bigger self dmg)",
          tri_beam_live['effects'][0]['type'] == 'affliction_damage' and tri_beam_live['effects'][0]['value'] == 45,
          tri_beam_live['effects'])

    game['turn'] = 'p1'
    hp_before_a = a['health']
    hp_before_b = b['health']
    play(game, 'p1', 'A', 'tri_beam', 'p2', 0)
    check("primed Tri-Beam deals 45 affliction damage",
          b['health'] == hp_before_b - 45, b['health'])
    check("primed Tri-Beam also stuns", any(s['type'] == 'stun' for s in b['status']), b['status'])
    check("primed Tri-Beam costs Tien 25 HP (not the base 15)", a['health'] == hp_before_a - 25, a['health'])
    check("Tri-Beam reverts to its base cost after being used primed",
          tri_beam_live['cost'] == base_tri_beam_cost, tri_beam_live['cost'])
    check("Tri-Beam reverts to its base effects after being used primed",
          tri_beam_live['effects'] == base_tri_beam_effects, tri_beam_live['effects'])

    # --- Path 2: primed, then never used -- must revert on its own once the window expires ---
    game2 = make_game()
    a2 = game2['players']['p1']['team'][0]
    a2['skills'] = [copy.deepcopy(skills_by_id['best_friend']), copy.deepcopy(skills_by_id['tri_beam'])]
    for s in a2['skills']: s['currentCooldown'] = 0
    tri_beam_live2 = next(s for s in a2['skills'] if s['id'] == 'tri_beam')

    play(game2, 'p1', 'A', 'best_friend', 'p1', 0)  # target_type is "self"; prime_skill's duration:1 -> 4 ticks (see game_engine.py comment for why); this already ticked once (p2's start_turn)
    check("Tri-Beam is primed immediately after Best Friend", tri_beam_live2['cost'] == {'random': 2},
          tri_beam_live2['cost'])

    ge.start_turn(game2, 'p1')  # tick 2/4
    ge.start_turn(game2, 'p2')  # tick 3/4
    check("still primed with time left on the window", tri_beam_live2['cost'] == {'random': 2},
          tri_beam_live2['cost'])
    ge.start_turn(game2, 'p1')  # tick 4/4 -- expires now
    check("Tri-Beam auto-reverts to its base cost once the priming window expires unused",
          tri_beam_live2['cost'] == base_tri_beam_cost, tri_beam_live2['cost'])
    check("Tri-Beam auto-reverts to its base effects once the priming window expires unused",
          tri_beam_live2['effects'] == base_tri_beam_effects, tri_beam_live2['effects'])


def test_yamcha_puar_becomes_spirit_ball_for_a_window():
    """Puar is a pure time-window transform (unlike Tri-Beam's one-shot
    combo payoff): using the primed 'Spirit Ball' does NOT immediately
    revert it back to Puar -- it stays Spirit Ball (gated only by its own
    cooldown) until the full 3-turn window itself runs out."""
    import characters
    if 'yamcha_saiyan_saga' not in characters.CHARACTERS:
        print("  SKIPPED: yamcha_saiyan_saga not in the current roster")
        return
    skills_by_id = {s['id']: s for s in characters.CHARACTERS['yamcha_saiyan_saga']['skills']}
    base_puar_cost = dict(skills_by_id['puar']['cost'])
    base_puar_name = skills_by_id['puar']['name']
    base_puar_cooldown = skills_by_id['puar']['cooldown']

    game = make_game()
    a = game['players']['p1']['team'][0]
    b = game['players']['p2']['team'][0]
    a['skills'] = [copy.deepcopy(skills_by_id['puar'])]
    a['skills'][0]['currentCooldown'] = 0
    puar_live = a['skills'][0]

    play(game, 'p1', 'A', 'puar', 'p1', 0)
    check("Puar grants Yamcha a 15-point shield", a.get('defense', 0) == 15, a.get('defense'))
    check("Puar transforms into Spirit Ball (name swap)", puar_live['name'] == 'Spirit Ball', puar_live['name'])
    check("Spirit Ball has its own cost", puar_live['cost'] == {'energy': 1, 'spirit': 1}, puar_live['cost'])
    check("Spirit Ball has its own cooldown (1)", puar_live['cooldown'] == 1, puar_live['cooldown'])

    # Spirit Ball ignores invulnerability specifically, but NOT destructible
    # defense or damage reduction -- prove that distinction directly.
    ge.add_status(b, {'type': 'invulnerable', 'duration': 10, 'tag': 'buff'})
    b['defense'] = 5

    # Use "Spirit Ball" (still in the puar slot) -- should NOT immediately
    # revert, just go on its own cooldown, unlike Tri-Beam's one-shot payoff.
    game['turn'] = 'p1'
    puar_live['currentCooldown'] = 0
    hp_before_b = b['health']
    play(game, 'p1', 'A', 'puar', 'p2', 0)
    check("Spirit Ball ignores invulnerability but is still absorbed by destructible defense (5 pts)",
          b['health'] == hp_before_b - (40 - 5) and b['defense'] == 0, (b['health'], b['defense']))
    check("using Spirit Ball does NOT revert it back to Puar", puar_live['name'] == 'Spirit Ball', puar_live['name'])
    check("Spirit Ball goes on its own cooldown after use", puar_live['currentCooldown'] > 0,
          puar_live['currentCooldown'])

    # duration:3 -> 2*3+2 = 8 ticks total; 2 already happened via the two
    # resolve_turn calls above, so 6 more reach the expiry point exactly.
    for _ in range(6):
        ge.start_turn(game, 'p1')  # ticks statuses for both players regardless of the player_id argument
    check("Spirit Ball auto-reverts back to Puar once the 3-turn window fully expires",
          puar_live['name'] == base_puar_name, puar_live['name'])
    check("reverted Puar has its original cost and cooldown back",
          puar_live['cost'] == base_puar_cost and puar_live['cooldown'] == base_puar_cooldown,
          (puar_live['cost'], puar_live['cooldown']))


def test_yamcha_puar_shield_expires_even_if_never_hit():
    """The key distinction the user drew: destructible defense never expires
    on its own (only shrinks by absorbing hits) -- this "points of damage"
    shield must disappear after its duration regardless of whether it was
    ever used, unlike the plain defense/ effect type."""
    game = make_game()
    a = game['players']['p1']['team'][0]
    ge.apply_effect({'type': 'expiring_defense', 'value': 15, 'duration': 1}, actor=a, targets=[a],
                     player=game['players']['p1'], opponent=game['players']['p2'], skill_classes=[])
    check("expiring_defense grants the shield immediately", a['defense'] == 15, a['defense'])
    ge.start_turn(game, 'p2')  # tick 1/2
    check("still active with a tick left", a['defense'] == 15, a['defense'])
    ge.start_turn(game, 'p1')  # tick 2/2 -- expires now, untouched
    check("the unused shield is removed once its duration runs out, even though nothing hit it",
          a['defense'] == 0, a['defense'])


def test_wolf_fang_fist_counters_marked_enemy():
    """Wolf Fang Fist marks a specific enemy: if THEY attempt any skill on
    their next turn, it's blocked entirely (never queued) and they take
    piercing damage instead. Also verifies the mark carries the 'invisible'
    flag the frontend uses to hide its status badge."""
    game = make_game()
    a = game['players']['p1']['team'][0]
    b = game['players']['p2']['team'][0]

    ge.apply_effect({'type': 'mark_for_counter', 'value': 20, 'duration': 1}, actor=a, targets=[b],
                     player=game['players']['p1'], opponent=game['players']['p2'], skill_classes=[])
    mark = next((s for s in b['status'] if s['type'] == 'marked_for_counter'), None)
    check("mark_for_counter applies a marked_for_counter status", mark is not None, b['status'])
    check("the mark is flagged invisible (frontend won't render a badge for it)",
          mark is not None and mark.get('invisible') is True, mark)

    game['turn'] = 'p2'
    b['skills'] = [{'id': 'poke', 'name': 'poke', 'cost': {}, 'target_type': 'enemy',
                     'effects': [{'type': 'damage', 'value': 30}], 'cooldown': 0, 'currentCooldown': 0}]
    hp_before_b = b['health']
    hp_before_a = a['health']
    blocked_msg = None
    try:
        ge.queue_move(game, 'p2', 'B', 'poke', 'p1', 0)
    except Exception as e:
        blocked_msg = str(e)
    check("the marked enemy's attempted skill is rejected, never queued", blocked_msg is not None, blocked_msg)
    check("the marked enemy takes 20 piercing damage for attempting it",
          b['health'] == hp_before_b - 20, b['health'])
    check("the would-be victim (Yamcha) took no damage -- the enemy's move never resolved",
          a['health'] == hp_before_a, a['health'])
    check("the mark is consumed (one-shot)",
          not any(s['type'] == 'marked_for_counter' for s in b['status']), b['status'])

    # Mark is gone now -- the enemy can act normally again.
    b['skills'][0]['currentCooldown'] = 0
    allowed = True
    try:
        ge.queue_move(game, 'p2', 'B', 'poke', 'p1', 0)
    except Exception:
        allowed = False
    check("with the mark consumed, the enemy can queue normally afterward", allowed)


def test_payment_must_cover_queued_costs():
    """Regression: resolve_turn used to accept ANY payment the player owned,
    including an empty one -- every queued skill was effectively free."""
    def costed_game(resources):
        game = make_game()
        a = game['players']['p1']['team'][0]
        a['skills'] = [{"id": "blast", "name": "Blast", "cost": {"energy": 1, "random": 1},
                        "target_type": "enemy", "effects": [{"type": "damage", "value": 20}],
                        "cooldown": 0, "currentCooldown": 0}]
        game['players']['p1']['resources'] = list(resources)
        return game

    def rejected(game, payment):
        try:
            ge.resolve_turn(game, payment)
            return False
        except Exception:
            return True

    game = costed_game(['energy', 'rage'])
    ge.queue_move(game, 'p1', 'A', 'blast', 'p2', 0)
    check("empty payment for a costed skill is rejected", rejected(game, []))
    check("rejected payment deals no damage", game['players']['p2']['team'][0]['health'] == 100)
    check("rejected payment takes no dice", sorted(game['players']['p1']['resources']) == ['energy', 'rage'],
          game['players']['p1']['resources'])
    check("underpaying (missing the random die) is rejected", rejected(game, ['energy']))
    wrong_type = costed_game(['energy', 'rage', 'rage'])
    ge.queue_move(wrong_type, 'p1', 'A', 'blast', 'p2', 0)
    check("paying the specific (energy) cost with the wrong type is rejected", rejected(wrong_type, ['rage', 'rage']))

    game = costed_game(['energy', 'rage', 'martial'])
    ge.queue_move(game, 'p1', 'A', 'blast', 'p2', 0)
    check("overpaying (an extra die) is rejected", rejected(game, ['energy', 'rage', 'martial']))

    game = costed_game(['energy', 'rage', 'martial'])
    ge.queue_move(game, 'p1', 'A', 'blast', 'p2', 0)
    ge.resolve_turn(game, ['energy', 'martial'])
    check("exact payment (random paid with any type) resolves the skill",
          game['players']['p2']['team'][0]['health'] == 80, game['players']['p2']['team'][0]['health'])
    check("exact payment removes exactly the paid dice", game['players']['p1']['resources'][:1] == ['rage'],
          game['players']['p1']['resources'])

    game = costed_game([])
    check("committing with nothing queued and no payment is still allowed", not rejected(game, []))


def test_queue_rejects_unaffordable_skills():
    """Regression: queue_move never looked at the dice pool at all."""
    game = make_game()
    game['players']['p1']['team'].append(make_char('A2'))
    for c in game['players']['p1']['team']:
        c['skills'] = [{"id": "blast", "name": "Blast", "cost": {"energy": 1, "random": 1},
                        "target_type": "enemy", "effects": [{"type": "damage", "value": 20}],
                        "cooldown": 0, "currentCooldown": 0}]

    def blocked(char_id):
        try:
            ge.queue_move(game, 'p1', char_id, 'blast', 'p2', 0)
            return False
        except Exception:
            return True

    game['players']['p1']['resources'] = ['rage', 'rage']
    check("skill whose specific type isn't in the pool can't be queued", blocked('A'))

    game['players']['p1']['resources'] = ['energy']
    check("skill whose random part can't be covered can't be queued", blocked('A'))

    game['players']['p1']['resources'] = ['energy', 'rage', 'martial']
    check("affordable skill queues", not blocked('A'))
    check("a 2nd skill that the pool can't cover together with the 1st is rejected", blocked('A2'))
    check("re-queueing the same character replaces its move instead of double-counting the cost", not blocked('A'))


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
