import random

# ---------------------------------------------------------------------------
# Status effect model
#
# Character-level statuses live in char['status'], a list of dicts:
#   {"type": <str>, "value": <num, optional>, "duration": <ticks>,
#    "classes": <list[str], optional>, "tag": "harmful"|"buff"}
#
# Player-level statuses (affect the chakra/Ki pool, not a character) live in
# player['status'] with the same shape, used by the chakra_* effects.
#
# "duration" is stored in ticks, where 1 round = 2 ticks (one tick removed
# each time ANY player's turn starts, so a stun/buff applied on your turn
# survives through the opponent's reply and expires at the start of your
# next turn). This matches the original stun convention.
#
# Recognized character-status types:
#   stun, silence, dot, hot, heal_block,
#   damage_taken_mod, damage_dealt_mod, heal_received_mod, heal_dealt_mod,
#   invulnerable, physical_invulnerable, chakra_invulnerable, mental_invulnerable,
#   dodge, counter, reflect
#
# Recognized player-status types:
#   chakra_restrict, chakra_drain_over_time
# ---------------------------------------------------------------------------

CHAKRA_TYPES = ["energy", "martial", "spirit", "rage"]


def roll_dice(amount):
    return [random.choice(CHAKRA_TYPES) for _ in range(amount)]


def remove_dice(player_state, amount, chakra_type=None):
    """Removes up to `amount` dice from a player's resource pool and returns
    what was actually removed. If chakra_type is given, only that type is
    removed (and fewer than `amount` may come out if the pool lacks them)."""
    pool = player_state['resources']
    removed = []
    if chakra_type:
        for _ in range(amount):
            if chakra_type in pool:
                pool.remove(chakra_type)
                removed.append(chakra_type)
            else:
                break
    else:
        for _ in range(min(amount, len(pool))):
            idx = random.randrange(len(pool))
            removed.append(pool.pop(idx))
    return removed


def check_payment_validity(player_resources, payment_list):
    temp_pool = player_resources.copy()
    for die in payment_list:
        if die in temp_pool:
            temp_pool.remove(die)
        else:
            return False
    return True


# --- status helpers ---------------------------------------------------------

def add_status(char, status):
    char.setdefault('status', []).append(status)


def consume_status(char, status_type):
    """Removes and returns the first status of this type (one-shot effects
    like dodge/counter/reflect). Returns None if not present."""
    statuses = char.get('status', [])
    for i, s in enumerate(statuses):
        if s.get('type') == status_type:
            return statuses.pop(i)
    return None


def has_status(status_list, status_type, target_classes=None):
    """If target_classes is None, just checks presence of the type.
    Otherwise (used for silence), a status entry blocks only if it has no
    'classes' of its own (blocks everything) or its classes intersect
    target_classes."""
    for s in status_list:
        if s.get('type') != status_type:
            continue
        if target_classes is None:
            return True
        s_classes = s.get('classes')
        if not s_classes or (set(s_classes) & set(target_classes)):
            return True
    return False


def remove_statuses(char, predicate):
    char['status'] = [s for s in char.get('status', []) if not predicate(s)]


def get_mod_multiplier(status_list, mod_type):
    total = sum(s.get('value', 0) for s in status_list if s.get('type') == mod_type)
    return max(0, 1 + total)


def is_invulnerable(target, skill_classes):
    status = target.get('status', [])
    if has_status(status, 'invulnerable'):
        return True
    for cls in (skill_classes or []):
        if has_status(status, f'{cls}_invulnerable'):
            return True
    return False


def is_harmful_blocked(target, skill_classes):
    """Shared guard for non-damage harmful effects (stun/silence/dot/etc.):
    blocked by invulnerability, or consumes a dodge if present."""
    if is_invulnerable(target, skill_classes):
        return True
    if consume_status(target, 'dodge'):
        return True
    return False


# --- core resolution --------------------------------------------------------

def apply_damage(target, amount, actor=None, ignore_defense=False,
                  ignore_reduction=False, ignore_invuln=False, skill_classes=None):
    if not target or target['health'] <= 0:
        return
    skill_classes = skill_classes or []
    status = target.setdefault('status', [])

    if not ignore_invuln:
        if is_invulnerable(target, skill_classes):
            return
        if consume_status(target, 'dodge'):
            return
        if consume_status(target, 'counter'):
            return
        if consume_status(target, 'reflect'):
            if actor:
                actor['health'] = max(0, actor['health'] - amount)
            return

    dealt_mult = get_mod_multiplier(actor.get('status', []), 'damage_dealt_mod') if actor else 1
    taken_mult = 1 if ignore_reduction else get_mod_multiplier(status, 'damage_taken_mod')
    final = max(0, round(amount * dealt_mult * taken_mult))

    if not ignore_defense and target.get('defense', 0) > 0:
        absorbed = min(target['defense'], final)
        target['defense'] -= absorbed
        final -= absorbed

    target['health'] = max(0, target['health'] - final)


def apply_heal(target, amount, actor=None):
    if not target or target['health'] <= 0:
        return
    status = target.get('status', [])
    if has_status(status, 'heal_block'):
        return
    dealt_mult = get_mod_multiplier(actor.get('status', []), 'heal_dealt_mod') if actor else 1
    received_mult = get_mod_multiplier(status, 'heal_received_mod')
    final = max(0, round(amount * dealt_mult * received_mult))
    target['health'] = min(target['maxHealth'], target['health'] + final)


def apply_effect(effect, actor, targets, player, opponent, skill_classes):
    etype = effect['type']

    # Any effect may set "target": "self" to hit the caster instead of the
    # skill's normally-resolved target(s) -- e.g. a skill that damages an
    # enemy while also buffing its own caster.
    effect_targets = [actor] if effect.get('target') == 'self' else targets

    if etype == 'damage':
        for t in effect_targets:
            apply_damage(t, effect['value'], actor=actor, skill_classes=skill_classes)

    elif etype == 'piercing_damage':
        for t in effect_targets:
            apply_damage(t, effect['value'], actor=actor, ignore_reduction=True, skill_classes=skill_classes)

    elif etype == 'affliction_damage':
        for t in effect_targets:
            apply_damage(t, effect['value'], actor=actor,
                         ignore_defense=True, ignore_reduction=True, ignore_invuln=True,
                         skill_classes=skill_classes)

    elif etype == 'self_damage':
        actor['health'] = max(0, actor['health'] - effect['value'])

    elif etype == 'aoe_damage':
        # Legacy shorthand: always hits the caster's whole opponent team,
        # regardless of the skill's target_type (kept for existing skills).
        for c in opponent['team']:
            if c['health'] > 0:
                apply_damage(c, effect['value'], actor=actor, skill_classes=skill_classes)

    elif etype == 'dot':
        for t in effect_targets:
            if t['health'] > 0 and not is_harmful_blocked(t, skill_classes):
                add_status(t, {'type': 'dot', 'value': effect['value'],
                                'duration': effect.get('duration', 1) * 2, 'tag': 'harmful'})

    elif etype == 'heal':
        for t in effect_targets:
            apply_heal(t, effect['value'], actor=actor)

    elif etype == 'hot':
        for t in effect_targets:
            if t['health'] > 0:
                add_status(t, {'type': 'hot', 'value': effect['value'],
                                'duration': effect.get('duration', 1) * 2, 'tag': 'buff'})

    elif etype == 'team_heal':
        for c in player['team']:
            apply_heal(c, effect['value'], actor=actor)

    elif etype == 'heal_block':
        for t in effect_targets:
            if t['health'] > 0 and not is_harmful_blocked(t, skill_classes):
                add_status(t, {'type': 'heal_block', 'duration': effect.get('duration', 1) * 2, 'tag': 'harmful'})

    elif etype == 'stun':
        for t in effect_targets:
            if t['health'] > 0 and not is_harmful_blocked(t, skill_classes):
                add_status(t, {'type': 'stun', 'duration': effect.get('duration', 1) * 2, 'tag': 'harmful'})

    elif etype == 'silence':
        for t in effect_targets:
            if t['health'] > 0 and not is_harmful_blocked(t, skill_classes):
                add_status(t, {'type': 'silence', 'classes': effect.get('classes'),
                                'duration': effect.get('duration', 1) * 2, 'tag': 'harmful'})

    elif etype == 'defense':
        for t in effect_targets:
            if t['health'] > 0:
                t['defense'] = t.get('defense', 0) + effect['value']

    elif etype == 'remove_defense':
        for t in effect_targets:
            t['defense'] = 0

    elif etype in ('damage_taken_mod', 'damage_dealt_mod', 'heal_received_mod', 'heal_dealt_mod'):
        tag = effect.get('tag', 'buff')
        for t in effect_targets:
            if t['health'] <= 0:
                continue
            if tag == 'harmful' and is_harmful_blocked(t, skill_classes):
                continue
            add_status(t, {'type': etype, 'value': effect['value'],
                            'duration': effect.get('duration', 1) * 2, 'tag': tag})

    elif etype in ('invulnerable', 'physical_invulnerable', 'chakra_invulnerable', 'mental_invulnerable'):
        for t in effect_targets:
            if t['health'] > 0:
                add_status(t, {'type': etype, 'duration': effect.get('duration', 1) * 2, 'tag': 'buff'})

    elif etype in ('dodge', 'counter', 'reflect'):
        for t in effect_targets:
            if t['health'] > 0:
                add_status(t, {'type': etype, 'duration': effect.get('duration', 1) * 2, 'tag': 'buff'})

    elif etype == 'cleanse':
        scope = effect.get('scope', 'harmful')  # 'harmful' | 'buff' | a specific status type
        for t in effect_targets:
            if scope in ('harmful', 'buff'):
                remove_statuses(t, lambda s: s.get('tag') == scope)
            else:
                remove_statuses(t, lambda s: s.get('type') == scope)

    elif etype == 'remove_chakra':
        remove_dice(opponent, effect.get('amount', 1), effect.get('chakra_type'))

    elif etype == 'steal_chakra':
        stolen = remove_dice(opponent, effect.get('amount', 1), effect.get('chakra_type'))
        player['resources'].extend(stolen)

    elif etype == 'chakra_regen':
        player['resources'].extend(roll_dice(effect.get('amount', 1)))

    elif etype == 'chakra_restrict':
        add_status(opponent, {'type': 'chakra_restrict', 'chakra_type': effect.get('chakra_type'),
                                'duration': effect.get('duration', 1) * 2, 'tag': 'harmful'})

    elif etype == 'chakra_drain_over_time':
        add_status(opponent, {'type': 'chakra_drain_over_time', 'value': effect.get('value', 1),
                                'duration': effect.get('duration', 1) * 2, 'tag': 'harmful'})


# --- turn lifecycle ----------------------------------------------------------

def tick_statuses(game_state):
    """Ticks down every status by one, applies DoT/HoT/chakra-drain payloads,
    and prunes anything that's expired. Runs at the start of every turn (for
    both players), matching the original stun-duration convention."""
    for p_key in ['p1', 'p2']:
        player = game_state['players'].get(p_key)
        if not player:
            continue

        for char in player['team']:
            active = []
            for s in char.get('status', []):
                if char['health'] > 0:
                    if s['type'] == 'dot':
                        char['health'] = max(0, char['health'] - s.get('value', 0))
                    elif s['type'] == 'hot':
                        char['health'] = min(char['maxHealth'], char['health'] + s.get('value', 0))
                s['duration'] -= 1
                if s['duration'] > 0:
                    active.append(s)
            char['status'] = active

        active_p = []
        for s in player.get('status', []):
            if s['type'] == 'chakra_drain_over_time':
                remove_dice(player, s.get('value', 1))
            s['duration'] -= 1
            if s['duration'] > 0:
                active_p.append(s)
        player['status'] = active_p


def start_turn(game_state, player_id):
    game_state['turn'] = player_id
    game_state['pending_moves'] = []

    # 1. Update Turn Count
    if 'turn_count' not in game_state: game_state['turn_count'] = 0
    game_state['turn_count'] += 1

    # 2. Global Status Tick
    tick_statuses(game_state)

    player = game_state['players'][player_id]

    # 3. Generate Dice
    alive_count = sum(1 for char in player['team'] if char['health'] > 0)

    # --- FIRST TURN RULE: Only 1 Die ---
    dice_to_roll = alive_count
    if game_state['turn_count'] == 1:
        dice_to_roll = 1
    # -----------------------------------

    if dice_to_roll > 0:
        new_dice = roll_dice(dice_to_roll)
        player['resources'].extend(new_dice)

    for char in player['team']:
        for skill in char['skills']:
            if skill['currentCooldown'] > 0: skill['currentCooldown'] -= 1

    return game_state


def queue_move(game_state, player_id, char_id, skill_id, target_pid, target_index):
    player = game_state['players'][player_id]
    if game_state['turn'] != player_id: raise Exception("Not your turn!")

    actor_char = next((c for c in player['team'] if c['id'] == char_id), None)

    if not actor_char: raise Exception("Character not found")

    used_skill = next((s for s in actor_char['skills'] if s['id'] == skill_id), None)
    if not used_skill: raise Exception("Skill not found")

    char_status = actor_char.get('status', [])
    if has_status(char_status, 'stun'):
        raise Exception(f"{actor_char['name']} is stunned and cannot act!")
    if has_status(char_status, 'silence', target_classes=used_skill.get('classes', [])):
        raise Exception(f"{actor_char['name']} is silenced and cannot use that skill!")

    if used_skill['currentCooldown'] > 0:
        raise Exception(f"{used_skill['name']} is on cooldown for {used_skill['currentCooldown']} more turn(s)!")

    for chakra_type in used_skill.get('cost', {}):
        if chakra_type == 'random':
            continue
        for s in player.get('status', []):
            if s['type'] == 'chakra_restrict' and s.get('chakra_type') in (None, chakra_type):
                raise Exception(f"{chakra_type.capitalize()} chakra is restricted!")

    current_queue = [m for m in game_state.get('pending_moves', []) if m['charId'] != char_id]

    new_move = {
        'playerId': player_id,
        'charId': char_id,
        'skillId': skill_id,
        'skillName': used_skill['name'],
        'targetPid': target_pid,
        'targetIndex': target_index,
        'cost': used_skill['cost']
    }
    current_queue.append(new_move)
    game_state['pending_moves'] = current_queue
    return game_state


def cancel_move(game_state, player_id, char_id):
    current_queue = game_state.get('pending_moves', [])
    new_queue = [m for m in current_queue if m['charId'] != char_id]
    game_state['pending_moves'] = new_queue
    return game_state


def resolve_turn(game_state, payment_list):
    moves = game_state.get('pending_moves', [])
    player_id = game_state['turn']
    player = game_state['players'][player_id]

    opponent_id = 'p2' if player_id == 'p1' else 'p1'
    opponent = game_state['players'][opponent_id]

    if not check_payment_validity(player['resources'], payment_list):
        raise Exception("Cheat detected!")

    for die in payment_list:
        player['resources'].remove(die)

    for move in moves:
        actor_char = next((c for c in player['team'] if c['id'] == move['charId']), None)
        skill = next((s for s in actor_char['skills'] if s['id'] == move['skillId']), None)

        if actor_char['health'] <= 0:
            continue

        skill_classes = skill.get('classes', [])
        target_type = skill.get('target_type', 'enemy')

        if target_type == 'enemy_team':
            targets = [c for c in opponent['team'] if c['health'] > 0]
        elif target_type == 'ally_team':
            targets = [c for c in player['team'] if c['health'] > 0]
        else:
            target_team = opponent['team']
            if target_type in ('ally', 'self'):
                target_team = player['team']
            target_char = None
            if 0 <= move['targetIndex'] < len(target_team):
                target_char = target_team[move['targetIndex']]
            targets = [target_char] if target_char else []

        effects = skill.get('effects', [])
        if not effects and 'effect' in skill: effects = [skill['effect']]

        for effect in effects:
            apply_effect(effect, actor_char, targets, player, opponent, skill_classes)

        skill['currentCooldown'] = skill['cooldown'] + 1

    p1_alive = sum(1 for c in game_state['players']['p1']['team'] if c['health'] > 0)
    p2_alive = sum(1 for c in game_state['players']['p2']['team'] if c['health'] > 0)

    if p1_alive == 0: game_state['winner'] = 'p2'
    elif p2_alive == 0: game_state['winner'] = 'p1'
    else:
        next_player = 'p2' if player_id == 'p1' else 'p1'
        start_turn(game_state, next_player)

    return game_state
