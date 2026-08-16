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
                "id": "kamehameha", "name": "Kamehameha", "description": "26 Dmg + Stun | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy",
                "image": "Goku_(Saiyan-Saga)_Kamehameha.png",
                "effects": [
                    {"type": "damage", "value": 26},
                    {"type": "stun", "duration": 1}
                ],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                "id": "kaioken", "name": "Kaioken",
                "description": "Self: +40% Dmg Dealt (2 Turns), 8 Self Dmg (strain) | 1 Spt",
                "cost": {"spirit": 1},
                "target_type": "self",
                "image": "kaioken.png",
                "effects": [
                    {"type": "damage_dealt_mod", "value": 0.4, "duration": 2, "tag": "buff", "target": "self"},
                    {"type": "self_damage", "value": 8}
                ],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "kaioken_attack", "name": "Kaioken Attack",
                "description": "32 Piercing Dmg (ignores dmg reduction) | 2 Mar",
                "cost": {"martial": 2},
                "target_type": "enemy",
                "classes": ["physical"],
                "image": "kaioken_attack.png",
                "effects": [{"type": "piercing_damage", "value": 32}],
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
