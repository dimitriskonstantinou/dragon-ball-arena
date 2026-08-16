# backend/characters.py

CHARACTERS = {
    # --- SAIYANS ---
    "goku": {
        "id": "goku", "name": "Goku", "image": "Goku.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "kamehameha", "name": "Kamehameha", "description": "30 Dmg + Stun | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy",
                "effects": [
                    {"type": "damage", "value": 30},
                    {"type": "stun", "duration": 1}
                ],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "meteor_smash", "name": "Meteor Smash", "description": "20 Dmg | 1 Mar",
                "cost": {"martial": 1},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 20}],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "spirit_bomb", "name": "Spirit Bomb",
                "description": "60 Affliction Dmg (ignores shields/reduction/invuln) | 2 Spt",
                "cost": {"spirit": 2},
                "target_type": "enemy",
                "effects": [{"type": "affliction_damage", "value": 60}],
                "cooldown": 4, "currentCooldown": 0
            }
        ]
    },
    "vegeta": {
        "id": "vegeta", "name": "Vegeta", "image": "Vegeta.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "galick_gun", "name": "Galick Gun", "description": "25 Dmg | 2 Eng",
                "cost": {"energy": 2},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 25}],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "dirty_fireworks", "name": "Dirty Fireworks", "description": "40 Dmg | 1 Rage, 1 Rand",
                "cost": {"rage": 1, "random": 1},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 40}],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "ozaru_crush", "name": "Giant Crush", "description": "20 Dmg + Self Shield 20 | 1 Mar",
                "cost": {"martial": 1},
                "target_type": "enemy",
                "effects": [
                    {"type": "damage", "value": 20},
                    {"type": "defense", "value": 20, "target": "self"}
                ],
                "cooldown": 0, "currentCooldown": 0
            }
        ]
    },
    "gohan": {
        "id": "gohan", "name": "Gohan", "image": "Gohan.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "masenko", "name": "Masenko", "description": "15 Dmg + Gain 1 Ki | 1 Eng",
                "cost": {"energy": 1},
                "target_type": "enemy",
                "effects": [
                    {"type": "damage", "value": 15},
                    {"type": "chakra_regen", "amount": 1}
                ],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "hidden_potential", "name": "Hidden Power",
                "description": "40 Dmg + Self +30% Dmg Dealt (2 Turns) | 1 Rage, 1 Rand",
                "cost": {"rage": 1, "random": 1},
                "target_type": "enemy",
                "effects": [
                    {"type": "damage", "value": 40},
                    {"type": "damage_dealt_mod", "value": 0.3, "duration": 2, "tag": "buff", "target": "self"}
                ],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "headbutt", "name": "Headbutt", "description": "Stun | 1 Mar",
                "cost": {"martial": 1},
                "target_type": "enemy",
                "effects": [{"type": "stun", "duration": 1}],
                "cooldown": 3, "currentCooldown": 0
            }
        ]
    },
    "trunks": {
        "id": "trunks", "name": "Trunks", "image": "Trunks.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "burning_attack", "name": "Burning Attack", "description": "20 Dmg | 1 Eng",
                "cost": {"energy": 1},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 20}],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "shining_slash", "name": "Shining Slash", "description": "30 Dmg | 1 Mar, 1 Rand",
                "cost": {"martial": 1, "random": 1},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 30}],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                "id": "finish_buster", "name": "Finish Buster",
                "description": "50 Piercing Dmg (ignores damage reduction) | 2 Eng",
                "cost": {"energy": 2},
                "target_type": "enemy",
                "classes": ["physical"],
                "effects": [{"type": "piercing_damage", "value": 50}],
                "cooldown": 3, "currentCooldown": 0
            }
        ]
    },

    # --- EARTHLINGS & NAMEKIANS ---
    "krillin": {
        "id": "krillin", "name": "Krillin", "image": "Krillin.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "destructo_disc", "name": "Destructo Disc", "description": "35 Dmg | 2 Spt",
                "cost": {"spirit": 2},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 35}],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "solar_flare", "name": "Solar Flare", "description": "Stun | 1 Eng",
                "cost": {"energy": 1},
                "target_type": "enemy",
                "effects": [{"type": "stun", "duration": 1}],
                "cooldown": 3, "currentCooldown": 0
            },
            {
                "id": "senzu_throw", "name": "Senzu Bean", "description": "Heal Ally 25 + Cleanse Harmful Effects | 1 Rand",
                "cost": {"random": 1},
                "target_type": "ally",  # Targets Ally
                "effects": [
                    {"type": "heal", "value": 25},
                    {"type": "cleanse", "scope": "harmful"}
                ],
                "cooldown": 1, "currentCooldown": 0
            }
        ]
    },
    "piccolo": {
        "id": "piccolo", "name": "Piccolo", "image": "Piccolo.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "special_beam_cannon", "name": "Special Beam",
                "description": "40 Piercing Dmg (ignores damage reduction) | 1 Eng, 1 Spt",
                "cost": {"energy": 1, "spirit": 1},
                "target_type": "enemy",
                "classes": ["chakra"],
                "effects": [{"type": "piercing_damage", "value": 40}],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "hellzone_grenade", "name": "Hellzone Grenade",
                "description": "15 Dmg + Bleed 5/turn to ALL enemies | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy_team",
                "effects": [
                    {"type": "damage", "value": 15},
                    {"type": "dot", "value": 5, "duration": 1}
                ],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "regeneration", "name": "Regenerate",
                "description": "Heal Self 10 + Regen 5/turn (2 Turns) | 1 Mar",
                "cost": {"martial": 1},
                "target_type": "self",  # Targets Self
                "effects": [
                    {"type": "heal", "value": 10},
                    {"type": "hot", "value": 5, "duration": 2}
                ],
                "cooldown": 1, "currentCooldown": 0
            }
        ]
    },

    # --- VILLAINS ---
    "frieza": {
        "id": "frieza", "name": "Frieza", "image": "Frieza.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "death_beam", "name": "Death Beam",
                "description": "25 Dmg + Restrict Enemy Energy Chakra (1 Turn) | 1 Eng",
                "cost": {"energy": 1},
                "target_type": "enemy",
                "effects": [
                    {"type": "damage", "value": 25},
                    {"type": "chakra_restrict", "chakra_type": "energy", "duration": 1}
                ],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "death_ball", "name": "Death Ball",
                "description": "50 Affliction Dmg (ignores shields/reduction/invuln) | 2 Rage",
                "cost": {"rage": 2},
                "target_type": "enemy",
                "effects": [{"type": "affliction_damage", "value": 50}],
                "cooldown": 3, "currentCooldown": 0
            },
            {
                "id": "psychokinesis", "name": "Telekinesis", "description": "Silence (Mental) | 1 Spt",
                "cost": {"spirit": 1},
                "target_type": "enemy",
                "classes": ["mental"],
                "effects": [{"type": "silence", "classes": ["mental"], "duration": 1}],
                "cooldown": 3, "currentCooldown": 0
            }
        ]
    },
    "cell": {
        "id": "cell", "name": "Cell", "image": "Cell.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "kamehameha_cell", "name": "Solar Kamehameha", "description": "35 Dmg | 1 Eng, 1 Rand",
                "cost": {"energy": 1, "random": 1},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 35}],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                "id": "absorb", "name": "Absorb Life", "description": "15 Dmg + 15 Heal + Steal 1 Ki | 1 Mar",
                "cost": {"martial": 1},
                "target_type": "enemy",
                # Special Multi-Effect: Damage Enemy, Heal Self, Steal a die from opponent's pool
                "effects": [
                    {"type": "damage", "value": 15},
                    {"type": "heal", "value": 15, "target": "self"},
                    {"type": "steal_chakra", "amount": 1}
                ],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "perfect_barrier", "name": "Perfect Barrier", "description": "Self Shield 25 | 1 Eng",
                "cost": {"energy": 1},
                "target_type": "self",
                "effects": [{"type": "defense", "value": 25}],
                "cooldown": 2, "currentCooldown": 0
            }
        ]
    },
    "raditz": {
        "id": "raditz", "name": "Raditz", "image": "Raditz.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "double_sunday", "name": "Double Sunday", "description": "20 Dmg + Remove 1 Enemy Ki | 1 Eng",
                "cost": {"energy": 1},
                "target_type": "enemy",
                "effects": [
                    {"type": "damage", "value": 20},
                    {"type": "remove_chakra", "amount": 1}
                ],
                "cooldown": 0, "currentCooldown": 0
            },
            {
                "id": "saturday_crush", "name": "Saturday Crush", "description": "Bleed 6/turn for 2 Turns | 2 Rage",
                "cost": {"rage": 2},
                "target_type": "enemy",
                "effects": [{"type": "dot", "value": 6, "duration": 2}],
                "cooldown": 3, "currentCooldown": 0
            },
            {
                "id": "tail_slap", "name": "Tail Slap", "description": "15 Dmg | 1 Mar",
                "cost": {"martial": 1},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 15}],
                "cooldown": 0, "currentCooldown": 0
            }
        ]
    },
    "nappa": {
        "id": "nappa", "name": "Nappa", "image": "Nappa.png",
        "health": 100, "maxHealth": 100, "status": [],
        "skills": [
            {
                "id": "giant_storm", "name": "Giant Storm",
                "description": "15 Dmg + Enemy Takes +25% Dmg (2 Turns) | 1 Rage",
                "cost": {"rage": 1},
                "target_type": "enemy",
                "effects": [
                    {"type": "damage", "value": 15},
                    {"type": "damage_taken_mod", "value": 0.25, "duration": 2, "tag": "harmful"}
                ],
                "cooldown": 1, "currentCooldown": 0
            },
            {
                "id": "break_cannon", "name": "Break Cannon", "description": "30 Dmg | 2 Mar",
                "cost": {"martial": 2},
                "target_type": "enemy",
                "effects": [{"type": "damage", "value": 30}],
                "cooldown": 2, "currentCooldown": 0
            },
            {
                "id": "tough_armor", "name": "Tough Skin",
                "description": "Immune to Physical Dmg (1 Turn) | 1 Rand",
                "cost": {"random": 1},
                "target_type": "self",  # Targets Self
                "effects": [{"type": "physical_invulnerable", "duration": 1}],
                "cooldown": 1, "currentCooldown": 0
            }
        ]
    }
}
