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
                "id": "kamehameha", "name": "Kamehameha", "description": "25 Dmg | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy",
                "image": "Goku_(Saiyan-Saga)_Kamehameha.png",
                "effects": [
                    {"type": "damage", "value": 25}
                ],
                "cooldown": 0, "currentCooldown": 0
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
                "description": ("Permanent transform. Costs 20 HP (1st-2nd use) / 40 HP (3rd+ use), "
                                 "1 Random (1st use) / 2 Random (every use after). "
                                 "1st use: Kamehameha +20 Dmg permanently, unlocks Kaioken Attack. "
                                 "Every use: Kaioken Attack damage increases. | 1 Rand"),
                "cost": {"random": 1},
                "target_type": "self",
                "image": "Goku_(Saiyan-Saga)_Kaioken.png",
                "effects": [
                    {"type": "add_stack", "stack_key": "kaioken"},
                    {"type": "self_damage_by_stack", "stack_key": "kaioken", "schedule": [20, 20, 40]},
                    {"type": "boost_skill_on_stack", "stack_key": "kaioken", "at_stack": 1,
                     "skill_id": "kamehameha", "effect_index": 0, "bonus": 20,
                     "new_description": "45 Dmg (Kaioken-boosted) | 1 Eng, 1 Rand"},
                    {"type": "unlock_skill_on_stack", "stack_key": "kaioken", "at_stack": 1,
                     "skill_id": "kaioken_attack"},
                    {"type": "scale_skill_by_stack", "stack_key": "kaioken",
                     "skill_id": "kaioken_attack", "effect_index": 0, "base": 40, "increment": 10,
                     "description_template": "{value} Piercing Dmg (ignores dmg reduction) | 1 Rage, 1 Mar"},
                    {"type": "set_skill_cost_on_stack", "stack_key": "kaioken", "at_stack": 1,
                     "skill_id": "kaioken", "cost": {"random": 2}}
                ],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                "id": "kaioken_attack", "name": "Kaioken Attack",
                "description": "Locked until Kaioken is used. 40 Piercing Dmg, +10 per further Kaioken use | 1 Rage, 1 Mar",
                "cost": {"rage": 1, "martial": 1},
                "target_type": "enemy",
                "classes": ["physical"],
                "image": "Goku_(Saiyan-Saga)_KaiokenAttack.png",
                "locked": True,
                "locked_reason": "Kaioken Attack requires Kaioken to be used first!",
                "effects": [{"type": "piercing_damage", "value": 40}],
                "cooldown": 1, "currentCooldown": 0
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
                "image": "Goku_(Saiyan-Saga)_Afterimage.png",
                "effects": [{"type": "invulnerable", "duration": 1}],
                "cooldown": 4, "currentCooldown": 0
            }
        ]
    },
    "piccolo_saiyan_saga": {
        "id": "piccolo_saiyan_saga", "name": "Piccolo (Saiyan Saga)", "image": "characters/Piccolo_(Saiyan-Saga).png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                # Charges this turn (visible "CHARGING HIT" marker on the
                # target, so the opponent sees it coming), then detonates
                # automatically at the start of Piccolo's next turn -- a flat,
                # unmitigated hit that ignores invulnerability/defense/reduction.
                "id": "special_beam_cannon", "name": "Special Beam Cannon",
                "description": ("Charges for 1 turn, visible to the enemy, then deals 40 Affliction Dmg "
                                 "(ignores invulnerability/defense/reduction) at the start of your next turn | 1 Eng, 1 Spt"),
                "cost": {"energy": 1, "spirit": 1},
                "target_type": "enemy",
                "classes": ["chakra"],
                "image": "Piccolo_(Saiyan-Saga)_SpecialBeamCannon.png",
                "effects": [{"type": "delayed_damage", "value": 40, "duration": 1}],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                # New engine mechanic (see game_engine.py's resolve_protection):
                # the next direct hit aimed at the protected ally lands on
                # Piccolo instead -- a real redirect, not a reskinned shield/heal.
                "id": "sacrifice", "name": "Sacrifice",
                "description": "The next attack aimed at this ally hits Piccolo instead | 1 Spt",
                "cost": {"spirit": 1},
                "target_type": "ally",
                "image": "Piccolo_(Saiyan-Saga)_Sacrifice.png",
                "effects": [{"type": "protect", "duration": 1}],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "explosive_breath_cannon", "name": "Explosive Breath Cannon",
                "description": "20 Dmg to ALL enemies | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy_team",
                "image": "Piccolo_(Saiyan-Saga)_ExplosiveBreathCannon.png",
                "effects": [{"type": "damage", "value": 20}],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                # Universal defensive skill (see Goku's afterimage_technique) --
                # same id/mechanic roster-wide, flavored here as a guard stance.
                "id": "afterimage_technique", "name": "Block",
                "description": "Untargetable/immune to all damage & harmful effects for 1 turn | 1 Rand",
                "cost": {"random": 1},
                "target_type": "self",
                "image": "Piccolo_(Saiyan-Saga)_Block.png",
                "effects": [{"type": "invulnerable", "duration": 1}],
                "cooldown": 4, "currentCooldown": 0
            }
        ]
    },

    # --- VILLAINS ---
    "raditz_saiyan_saga": {
        "id": "raditz_saiyan_saga", "name": "Raditz (Saiyan Saga)", "image": "characters/Raditz.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                # Ignores whichever enemy was clicked to fire it -- the actual
                # targets are randomly sampled from the opponent's living team.
                "id": "double_sunday", "name": "Double Sunday",
                "description": "25 Dmg to 2 random enemies | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy",
                "image": "Raditz_DoubleSunday.png",
                "effects": [{"type": "random_multi_damage", "value": 25, "count": 2}],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                # remove_defense fires first, so there's nothing left for the
                # piercing hit to absorb into -- the full 40 always lands on HP.
                "id": "shining_friday", "name": "Shining Friday",
                "description": "Destroys any destructible defense, then 40 Piercing Dmg | 2 Rage",
                "cost": {"rage": 2},
                "target_type": "enemy",
                "image": "Raditz_ShiningFriday.png",
                "effects": [
                    {"type": "remove_defense"},
                    {"type": "piercing_damage", "value": 40}
                ],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "knee_attack", "name": "Knee Attack",
                "description": "25 Dmg + Stun 1 turn | 1 Mar, 1 Rand",
                "cost": {"martial": 1, "random": 1},
                "target_type": "enemy",
                "image": "Raditz_KneeAttack.png",
                "effects": [
                    {"type": "damage", "value": 25},
                    {"type": "stun", "duration": 1}
                ],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                # Universal defensive skill (see Goku's afterimage_technique) --
                # same id/mechanic roster-wide, flavored here to match Piccolo's "Block".
                "id": "afterimage_technique", "name": "Block",
                "description": "Untargetable/immune to all damage & harmful effects for 1 turn | 1 Rand",
                "cost": {"random": 1},
                "target_type": "self",
                "image": "Raditz_Block.png",
                "effects": [{"type": "invulnerable", "duration": 1}],
                "cooldown": 4, "currentCooldown": 0
            }
        ]
    },
    # The rest of the roster was deleted to be rebuilt from scratch, one
    # character at a time, under the saga-versioned id + universal 4th
    # skill + real skill icons conventions established with Goku above.
}
