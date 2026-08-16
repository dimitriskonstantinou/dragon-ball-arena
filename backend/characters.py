# backend/characters.py

CHARACTERS = {
    # --- SAIYANS ---
    # Saga-versioned roster: this is early Goku (Saiyan Saga) specifically --
    # later sagas (Namek, Cell, etc.) get their own separate entries
    # (e.g. "goku_namek_saga") rather than replacing this one, so old and
    # new versions can coexist in the roster.
    "goku_saiyan_saga": {
        "id": "goku_saiyan_saga", "name": "Goku (Saiyan Saga)", "image": "characters/Goku_(Saiyan-Saga).png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "kamehameha", "name": "Kamehameha", "description": "25 Dmg + Stun | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy",
                "image": "Goku_(Saiyan-Saga)_Kamehameha.png",
                "effects": [
                    {"type": "damage", "value": 25},
                    {"type": "stun", "duration": 1}
                ],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                # Permanent, repeatable transformation -- not a temporary buff.
                # Each use: costs HP (escalating, see schedule below), and on
                # the very first use it permanently boosts Kamehameha +20 dmg
                # and unlocks Kaioken Attack. Every use (including the first)
                # also re-scales Kaioken Attack's damage upward. No cooldown:
                # the escalating self-damage is the only limiter, by design --
                # Goku can use this as many times as he wants, even to his death.
                "id": "kaioken", "name": "Kaioken",
                "description": ("Permanent transform. Costs 20 HP (1st-2nd use) / 40 HP (3rd+ use). "
                                 "1st use: Kamehameha +20 Dmg permanently, unlocks Kaioken Attack. "
                                 "Every use: Kaioken Attack damage increases. | 1 Spt"),
                "cost": {"spirit": 1},
                "target_type": "self",
                "image": "kaioken.png",
                "effects": [
                    {"type": "add_stack", "stack_key": "kaioken"},
                    {"type": "self_damage_by_stack", "stack_key": "kaioken", "schedule": [20, 20, 40]},
                    {"type": "boost_skill_on_stack", "stack_key": "kaioken", "at_stack": 1,
                     "skill_id": "kamehameha", "effect_index": 0, "bonus": 20,
                     "new_description": "45 Dmg + Stun (Kaioken-boosted) | 1 Eng, 1 Rand"},
                    {"type": "unlock_skill_on_stack", "stack_key": "kaioken", "at_stack": 1,
                     "skill_id": "kaioken_attack"},
                    {"type": "scale_skill_by_stack", "stack_key": "kaioken",
                     "skill_id": "kaioken_attack", "effect_index": 0, "base": 30, "increment": 10,
                     "description_template": "{value} Piercing Dmg (ignores dmg reduction) | 2 Mar"}
                ],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "kaioken_attack", "name": "Kaioken Attack",
                "description": "Locked until Kaioken is used. 30 Piercing Dmg, +10 per further Kaioken use | 2 Mar",
                "cost": {"martial": 2},
                "target_type": "enemy",
                "classes": ["physical"],
                "image": "kaioken_attack.png",
                "locked": True,
                "locked_reason": "Kaioken Attack requires Kaioken to be used first!",
                "effects": [{"type": "piercing_damage", "value": 30}],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                # Universal defensive skill -- every character gets this exact
                # skill eventually (id/effect stay identical roster-wide, like
                # Naruto Arena's Substitution). DBZ-flavored as the
                # afterimage/Zanzoken evasion technique.
                "id": "afterimage_technique", "name": "Afterimage Technique",
                "description": "Untargetable/immune to all damage & harmful effects for 1 turn | 1 Rand",
                "cost": {"random": 1},
                "target_type": "self",
                "image": "afterimage_technique.png",
                "effects": [{"type": "invulnerable", "duration": 1}],
                "cooldown": 3, "currentCooldown": 0
            }
        ]
    },
    # The rest of the roster was deleted to be rebuilt from scratch, one
    # character at a time, under the saga-versioned id + universal 4th
    # skill + real skill icons conventions established with Goku above.
}
