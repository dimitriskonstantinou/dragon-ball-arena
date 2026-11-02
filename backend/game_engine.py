import copy
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
#   dodge, counter, reflect, protected,
#   delayed_damage (visible "charging" marker; detonates on its last tick --
#   see tick_statuses -- rather than every tick like dot)
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


def total_cost(costs):
    """Sums a list of skill cost dicts into (specific_counts, random_count),
    e.g. [{'energy': 1, 'random': 1}, {'energy': 1}] -> ({'energy': 2}, 1)."""
    specific = {}
    random_needed = 0
    for cost in costs:
        for ki_type, amount in cost.items():
            if ki_type == 'random':
                random_needed += amount
            else:
                specific[ki_type] = specific.get(ki_type, 0) + amount
    return specific, random_needed


def can_afford(pool, costs):
    """True if `pool` can pay every cost in `costs` at once: each specific
    type must be covered by dice of that type, and whatever is left over
    must cover the combined random requirement."""
    specific, random_needed = total_cost(costs)
    for ki_type, amount in specific.items():
        if pool.count(ki_type) < amount:
            return False
    return len(pool) - sum(specific.values()) >= random_needed


def payment_matches_costs(payment_list, costs):
    """True if `payment_list` pays `costs` exactly: no dice short, no dice
    extra, and every specific requirement paid with its own type (random
    requirements accept any type)."""
    specific, random_needed = total_cost(costs)
    if len(payment_list) != sum(specific.values()) + random_needed:
        return False
    return all(payment_list.count(ki_type) >= amount for ki_type, amount in specific.items())


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


def resolve_protection(target, player, opponent):
    """If `target` has an active 'protected' status (from the 'protect'
    effect), consumes it (one-shot) and returns the protector to redirect
    the hit to instead -- or None if there's no protection, or the
    protector has since died, in which case the hit lands on `target` as
    normal. Only wired into direct single-target damage (damage/
    piercing_damage/affliction_damage), not aoe_damage or dot."""
    protect_status = consume_status(target, 'protected')
    if not protect_status:
        return None
    protector_id = protect_status.get('protector_id')
    for team in (player['team'], opponent['team']):
        for c in team:
            if c['id'] == protector_id and c['health'] > 0:
                return c
    return None


# --- core resolution --------------------------------------------------------

def apply_damage(target, amount, actor=None, ignore_defense=False,
                  ignore_reduction=False, ignore_invuln=False, ignore_reactive=None, skill_classes=None):
    """ignore_invuln skips the general/class invulnerability check specifically.
    ignore_reactive skips dodge/counter/reflect specifically -- a DIFFERENT
    thing (those are one-shot reactive defenses, not a standing immunity).
    If ignore_reactive is left as None, it defaults to whatever ignore_invuln
    was, which is what keeps affliction_damage's existing "ignores
    everything" behavior working unchanged. Pass ignore_reactive=False
    explicitly for a damage type that should bypass ONLY invulnerability
    while still respecting dodge/counter/reflect."""
    if not target or target['health'] <= 0:
        return
    skill_classes = skill_classes or []
    status = target.setdefault('status', [])
    if ignore_reactive is None:
        ignore_reactive = ignore_invuln

    if not ignore_invuln:
        if is_invulnerable(target, skill_classes):
            return
    if not ignore_reactive:
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
            real_target = resolve_protection(t, player, opponent) or t
            apply_damage(real_target, effect['value'], actor=actor, skill_classes=skill_classes)

    elif etype == 'piercing_damage':
        for t in effect_targets:
            real_target = resolve_protection(t, player, opponent) or t
            apply_damage(real_target, effect['value'], actor=actor, ignore_reduction=True, skill_classes=skill_classes)

    elif etype == 'affliction_damage':
        for t in effect_targets:
            real_target = resolve_protection(t, player, opponent) or t
            apply_damage(real_target, effect['value'], actor=actor,
                         ignore_defense=True, ignore_reduction=True, ignore_invuln=True,
                         skill_classes=skill_classes)

    elif etype == 'damage_ignore_invuln':
        # Narrower than affliction_damage: bypasses ONLY invulnerability
        # (general + class-specific). Still absorbed by destructible defense,
        # still reduced by damage_taken_mod, and still blockable by
        # dodge/counter/reflect.
        for t in effect_targets:
            real_target = resolve_protection(t, player, opponent) or t
            apply_damage(real_target, effect['value'], actor=actor,
                         ignore_invuln=True, ignore_reactive=False, skill_classes=skill_classes)

    elif etype == 'self_damage':
        actor['health'] = max(0, actor['health'] - effect['value'])

    elif etype == 'random_multi_damage':
        # Ignores the resolved target entirely (like aoe_damage) -- the UI
        # still requires clicking *a* target to fire the skill, but the
        # actual targets are randomly sampled from the opponent's living team.
        alive_enemies = [c for c in opponent['team'] if c['health'] > 0]
        chosen = random.sample(alive_enemies, min(effect.get('count', 1), len(alive_enemies)))
        for t in chosen:
            real_target = resolve_protection(t, player, opponent) or t
            apply_damage(real_target, effect['value'], actor=actor, skill_classes=skill_classes)

    elif etype == 'delayed_damage':
        # Visible "charging" marker -- deals no damage now. Detonates as a
        # flat, unmitigated hit (ignores invulnerability/defense/reduction,
        # like affliction) on its last tick; see tick_statuses(). The status
        # itself is what makes the charge-up visible to the opponent.
        for t in effect_targets:
            if t['health'] > 0:
                add_status(t, {'type': 'delayed_damage', 'value': effect['value'],
                                'duration': effect.get('duration', 1) * 2, 'tag': 'harmful'})

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

    elif etype == 'protect':
        # Grants the target ally a one-shot redirect: the next direct
        # damage instance (damage/piercing_damage/affliction_damage) aimed
        # at them lands on the caster instead. See resolve_protection().
        for t in effect_targets:
            if t['health'] > 0:
                add_status(t, {'type': 'protected', 'protector_id': actor['id'],
                                'duration': effect.get('duration', 1) * 2, 'tag': 'buff'})

    elif etype == 'mark_for_counter':
        # Invisible trap: if the marked enemy attempts ANY skill on their
        # next turn, it's blocked entirely and they take piercing damage
        # instead -- see the counter-check at the top of queue_move(). The
        # 'invisible' flag means the frontend won't render a status badge
        # for it, so the target has no warning.
        for t in effect_targets:
            if t['health'] > 0:
                add_status(t, {'type': 'marked_for_counter', 'value': effect.get('value', 20),
                                'duration': effect.get('duration', 1) * 2, 'tag': 'harmful', 'invisible': True})

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
        # PERMANENT destructible defense -- absorbs damage until depleted,
        # never expires on its own. See expiring_defense below for the
        # different, time-limited version.
        for t in effect_targets:
            if t['health'] > 0:
                t['defense'] = t.get('defense', 0) + effect['value']

    elif etype == 'remove_defense':
        for t in effect_targets:
            t['defense'] = 0

    elif etype == 'expiring_defense':
        # A shield that ALSO has a clock on it: absorbs damage the same way
        # as plain 'defense', but whatever of it is still unused gets pulled
        # back off when the duration runs out (see tick_statuses) -- unlike
        # 'defense', which only ever shrinks by actually being hit.
        for t in effect_targets:
            if t['health'] > 0:
                t['defense'] = t.get('defense', 0) + effect['value']
                add_status(t, {'type': 'expiring_defense', 'value': effect['value'],
                                'duration': effect.get('duration', 1) * 2, 'tag': 'buff'})

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

    # --- permanent stacking transformations (e.g. Kaioken) ------------------
    # Unlike statuses, these never expire and persist for the rest of the
    # match; they work by directly rewriting the caster's own skill dicts
    # (which already live per-match, deep-copied off the CHARACTERS template
    # -- see queue_move's currentCooldown mutation for the existing precedent).

    elif etype == 'add_stack':
        stacks = actor.setdefault('stacks', {})
        stacks[effect['stack_key']] = stacks.get(effect['stack_key'], 0) + 1

    elif etype == 'self_damage_by_stack':
        count = actor.get('stacks', {}).get(effect['stack_key'], 1)
        schedule = effect['schedule']
        dmg = schedule[min(count - 1, len(schedule) - 1)] if schedule else 0
        actor['health'] = max(0, actor['health'] - dmg)

    elif etype == 'boost_skill_on_stack':
        # One-time permanent bump to another skill's value, applied only the
        # instant the stack counter hits `at_stack` (so it fires exactly once).
        count = actor.get('stacks', {}).get(effect['stack_key'], 0)
        if count == effect['at_stack']:
            target = next((s for s in actor.get('skills', []) if s['id'] == effect['skill_id']), None)
            if target:
                target['effects'][effect.get('effect_index', 0)]['value'] += effect['bonus']
                if 'new_description' in effect:
                    target['description'] = effect['new_description']

    elif etype == 'unlock_skill_on_stack':
        count = actor.get('stacks', {}).get(effect['stack_key'], 0)
        if count == effect['at_stack']:
            target = next((s for s in actor.get('skills', []) if s['id'] == effect['skill_id']), None)
            if target:
                target['locked'] = False

    elif etype == 'scale_skill_by_stack':
        # Recomputed every time (not one-shot): value = base + increment * (stacks - 1).
        count = actor.get('stacks', {}).get(effect['stack_key'], 0)
        if count >= 1:
            target = next((s for s in actor.get('skills', []) if s['id'] == effect['skill_id']), None)
            if target:
                new_value = effect['base'] + effect['increment'] * (count - 1)
                target['effects'][effect.get('effect_index', 0)]['value'] = new_value

    elif etype == 'set_skill_cost_on_stack':
        # One-shot: at the exact stack count `at_stack`, permanently replaces
        # another skill's (or this same skill's) Ki cost -- e.g. Kaioken
        # costing more of itself to re-cast after the first use.
        count = actor.get('stacks', {}).get(effect['stack_key'], 0)
        if count == effect['at_stack']:
            target = next((s for s in actor.get('skills', []) if s['id'] == effect['skill_id']), None)
            if target:
                target['cost'] = dict(effect['cost'])
                if 'description_template' in effect:
                    target['description'] = effect['description_template'].format(value=new_value)

    elif etype == 'prime_skill':
        # Temporary, REVERSIBLE combo setup (unlike the permanent stack
        # effects above): swaps another skill's cost/effects/description/
        # name/image to a "primed" version (skill_id can even be the SAME
        # skill casting this effect -- e.g. a skill that turns itself into a
        # different one for a while), remembering the originals so
        # unprime_skill (optional -- only needed if using the primed skill
        # should immediately revert it, like a one-shot combo payoff) or
        # this priming simply expiring (see tick_statuses) can restore them.
        # Re-priming while already primed is a safe no-op on the saved
        # originals (the guard below only saves them once).
        #
        # Duration formula is `2*N + 2` ticks for "usable during the
        # caster's next N turns", NOT a flat multiplier: every other
        # duration in this file counts ticks until the EFFECT'S OWN TARGET
        # can next act (e.g. a stun on the opponent needs 2 ticks to cover
        # their very next turn). But priming is a self-buff meant to be
        # usable on the CASTER'S own turns -- reaching the caster's next
        # turn already costs 2 ticks (the opponent's intervening turn), and
        # it must still be active *after* that tick, not expire on it, and
        # that pattern repeats for each further usable turn -- hence 2N, +2
        # for the initial reach. (N=1 -> 4 ticks; N=3 -> 8 ticks.)
        for t in effect_targets:
            target = next((s for s in t.get('skills', []) if s['id'] == effect['skill_id']), None)
            if not target:
                continue
            if 'base_cost' not in target:
                target['base_cost'] = dict(target['cost'])
                target['base_effects'] = copy.deepcopy(target['effects'])
                target['base_description'] = target.get('description')
                target['base_name'] = target.get('name')
                target['base_image'] = target.get('image')
                target['base_cooldown'] = target.get('cooldown')
                target['base_target_type'] = target.get('target_type')
            target['cost'] = dict(effect['primed_cost'])
            target['effects'] = copy.deepcopy(effect['primed_effects'])
            if 'primed_description' in effect:
                target['description'] = effect['primed_description']
            if 'primed_name' in effect:
                target['name'] = effect['primed_name']
            if 'primed_image' in effect:
                target['image'] = effect['primed_image']
            if 'primed_cooldown' in effect:
                target['cooldown'] = effect['primed_cooldown']
            if 'primed_target_type' in effect:
                target['target_type'] = effect['primed_target_type']
            add_status(t, {'type': 'primed_mark', 'mark': effect['mark'], 'skill_id': effect['skill_id'],
                            'duration': effect.get('duration', 1) * 2 + 2, 'tag': 'buff'})

    elif etype == 'unprime_skill':
        # Restores a primed skill back to its base cost/effects/description/
        # name/image. Only needed as an effect on the primed skill itself
        # for "reverts the instant it's used" combos (e.g. Tri-Beam); for a
        # pure time-window transform (e.g. "becomes a different skill for
        # 3 turns, usable more than once"), skip this and let tick_statuses'
        # expiry path be the only revert.
        for t in effect_targets:
            target = next((s for s in t.get('skills', []) if s['id'] == effect['skill_id']), None)
            if target and 'base_cost' in target:
                target['cost'] = target.pop('base_cost')
                target['effects'] = target.pop('base_effects')
                if 'base_description' in target:
                    target['description'] = target.pop('base_description')
                if 'base_name' in target:
                    target['name'] = target.pop('base_name')
                if 'base_image' in target:
                    target['image'] = target.pop('base_image')
                if 'base_cooldown' in target:
                    target['cooldown'] = target.pop('base_cooldown')
                if 'base_target_type' in target:
                    target['target_type'] = target.pop('base_target_type')
            remove_statuses(t, lambda s: s.get('type') == 'primed_mark' and s.get('mark') == effect.get('mark'))


# --- per-player view ---------------------------------------------------------

# Server-only fields on a player entry: socket id and account id.
PRIVATE_PLAYER_FIELDS = ('id', 'user_id')


def view_for(game_state, role):
    """What `role` is allowed to see -- a stripped deep copy, never the live
    state. Removes: both players' socket/account ids, the opponent's queued
    moves (only the active player sees the queue), and 'invisible' statuses
    on the viewer's own characters (e.g. a counter-trap placed on them; the
    player who placed it still sees it)."""
    view = copy.deepcopy(game_state)
    for player in view['players'].values():
        for field in PRIVATE_PLAYER_FIELDS:
            player.pop(field, None)
    if view.get('turn') != role:
        view['pending_moves'] = []
    for char in view['players'][role]['team']:
        char['status'] = [s for s in char.get('status', []) if not s.get('invisible')]
    return view


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
                    elif s['type'] == 'delayed_damage' and s['duration'] <= 1:
                        # Last tick before expiry -- detonate now, unmitigated
                        # (ignores invulnerability/defense/reduction), then let
                        # the duration check below prune the marker as usual.
                        char['health'] = max(0, char['health'] - s.get('value', 0))
                    elif s['type'] == 'expiring_defense' and s['duration'] <= 1:
                        # Time's up -- pull back whatever of this shield is
                        # still unused (can't go negative, can't remove more
                        # than this specific grant contributed).
                        char['defense'] = max(0, char.get('defense', 0) - s.get('value', 0))
                if s['type'] == 'primed_mark' and s['duration'] <= 1:
                    # The priming window ran out before the primed skill got
                    # used -- revert it back to its base cost/effects/
                    # description/name/image (mirrors unprime_skill's own logic).
                    target = next((sk for sk in char.get('skills', []) if sk['id'] == s.get('skill_id')), None)
                    if target and 'base_cost' in target:
                        target['cost'] = target.pop('base_cost')
                        target['effects'] = target.pop('base_effects')
                        if 'base_description' in target:
                            target['description'] = target.pop('base_description')
                        if 'base_name' in target:
                            target['name'] = target.pop('base_name')
                        if 'base_image' in target:
                            target['image'] = target.pop('base_image')
                        if 'base_cooldown' in target:
                            target['cooldown'] = target.pop('base_cooldown')
                        if 'base_target_type' in target:
                            target['target_type'] = target.pop('base_target_type')
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


def resolve_target(game_state, player_id, actor_char, skill, target_pid, target_index):
    """Validates the client's chosen target against the skill's target_type
    and returns the (target_pid, target_index) to store on the move. 'self'
    and team skills don't trust the click at all -- the server picks the
    side (and for 'self', the caster) itself."""
    opponent_id = 'p2' if player_id == 'p1' else 'p1'
    own_team = game_state['players'][player_id]['team']
    target_type = skill.get('target_type', 'enemy')

    if target_type == 'self':
        return player_id, own_team.index(actor_char)
    if target_type == 'enemy_team':
        return opponent_id, 0
    if target_type == 'ally_team':
        return player_id, 0

    expected_pid = opponent_id if target_type == 'enemy' else player_id
    if target_pid != expected_pid:
        side = "an enemy" if target_type == 'enemy' else "an ally"
        raise Exception(f"{skill['name']} must target {side}!")
    if not isinstance(target_index, int) or isinstance(target_index, bool):
        raise Exception("Invalid target!")
    team = game_state['players'][expected_pid]['team']
    if not 0 <= target_index < len(team):
        raise Exception("Invalid target!")
    if team[target_index]['health'] <= 0:
        raise Exception(f"{team[target_index]['name']} has already been defeated!")
    return expected_pid, target_index


def queue_move(game_state, player_id, char_id, skill_id, target_pid, target_index):
    player = game_state['players'][player_id]
    if game_state['turn'] != player_id: raise Exception("Not your turn!")

    actor_char = next((c for c in player['team'] if c['id'] == char_id), None)

    if not actor_char: raise Exception("Character not found")
    if actor_char['health'] <= 0:
        raise Exception(f"{actor_char['name']} has been defeated and cannot act!")

    used_skill = next((s for s in actor_char['skills'] if s['id'] == skill_id), None)
    if not used_skill: raise Exception("Skill not found")

    if used_skill.get('locked'):
        raise Exception(used_skill.get('locked_reason', f"{used_skill['name']} is locked."))

    char_status = actor_char.get('status', [])
    if has_status(char_status, 'stun'):
        raise Exception(f"{actor_char['name']} is stunned and cannot act!")
    if has_status(char_status, 'silence', target_classes=used_skill.get('classes', [])):
        raise Exception(f"{actor_char['name']} is silenced and cannot use that skill!")

    if used_skill['currentCooldown'] > 0:
        raise Exception(f"{used_skill['name']} is on cooldown for {used_skill['currentCooldown']} more turn(s)!")

    # Before the counter-mark check, so an invalid click can't trip the trap.
    target_pid, target_index = resolve_target(game_state, player_id, actor_char, used_skill,
                                              target_pid, target_index)

    # Only trips once we know this would otherwise be a legitimate queue
    # attempt (not blocked by stun/silence/lock/cooldown already) -- a
    # marked character who genuinely tries to act gets countered: their
    # move never queues, and they take piercing damage instead.
    counter_mark = consume_status(actor_char, 'marked_for_counter')
    if counter_mark:
        dmg = counter_mark.get('value', 20)
        apply_damage(actor_char, dmg, ignore_reduction=True)
        raise Exception(f"{actor_char['name']}'s attack was countered! Took {dmg} piercing damage.")

    for chakra_type in used_skill.get('cost', {}):
        if chakra_type == 'random':
            continue
        for s in player.get('status', []):
            if s['type'] == 'chakra_restrict' and s.get('chakra_type') in (None, chakra_type):
                raise Exception(f"{chakra_type.capitalize()} chakra is restricted!")

    current_queue = [m for m in game_state.get('pending_moves', []) if m['charId'] != char_id]

    # The pool must cover this skill together with everything already queued
    # (excluding this character's own previous queue entry, which this replaces).
    if not can_afford(player['resources'], [m['cost'] for m in current_queue] + [used_skill['cost']]):
        raise Exception(f"Not enough Ki for {used_skill['name']}!")

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
    # Owning the dice isn't enough -- they must pay the queued costs exactly,
    # otherwise an empty payment would cast every queued skill for free.
    if not payment_matches_costs(payment_list, [m['cost'] for m in moves]):
        raise Exception("Payment doesn't match the cost of your queued skills!")

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
