"""
Pydantic models for game content (characters, skills, effects).

These models are the single definition of what a valid content file looks
like. They are used two ways:
  - content_loader.py validates every file in backend/content/ against them
    (shape, types, ranges, unknown/typo'd fields) before the server starts;
  - `python content_schema.py` regenerates the JSON Schema files in
    backend/content/ that give VS Code autocomplete + live validation while
    editing character files (test_content.py fails if they're out of date).

Validation only -- no game logic lives here. Fields mirror exactly what
game_engine.apply_effect reads; optional fields keep the engine's defaults
(e.g. duration defaults to 1 turn) and are left out of the loaded data when
not written, so the engine sees the same dicts it always did.
"""
import json
import os
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag

CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'content')

KiType = Literal['energy', 'martial', 'spirit', 'rage']
SkillClass = Literal['physical', 'chakra', 'mental']
TargetType = Literal['enemy', 'ally', 'self', 'enemy_team', 'ally_team']

Amount = Annotated[int, Field(ge=0, le=999)]        # damage / heal / shield points
Turns = Annotated[int, Field(ge=1, le=20)]          # durations, in turns (engine converts to ticks)
Percent = Annotated[float, Field(ge=-1, le=5)]      # damage/heal modifiers, e.g. -0.25 = -25%


class Strict(BaseModel):
    # Unknown keys are errors: a typo like "vlaue" must not load silently.
    model_config = ConfigDict(extra='forbid')


class Cost(Strict):
    energy: int = Field(default=None, ge=1, le=10)
    martial: int = Field(default=None, ge=1, le=10)
    spirit: int = Field(default=None, ge=1, le=10)
    rage: int = Field(default=None, ge=1, le=10)
    random: int = Field(default=None, ge=1, le=10)


class EffectBase(Strict):
    target: Literal['self'] = Field(
        default=None, description="Apply to the caster instead of the skill's resolved target(s).")


# --- effect types (one model per engine branch) ------------------------------

class _ValueEffect(EffectBase):
    value: Amount


class Damage(_ValueEffect):
    type: Literal['damage']


class PiercingDamage(_ValueEffect):
    type: Literal['piercing_damage'] = Field(description="Ignores damage reduction (not destructible defense).")


class AfflictionDamage(_ValueEffect):
    type: Literal['affliction_damage'] = Field(description="Ignores reduction, defense, invulnerability and reactive defenses.")


class DamageIgnoreInvuln(_ValueEffect):
    type: Literal['damage_ignore_invuln'] = Field(description="Ignores invulnerability only.")


class SelfDamage(_ValueEffect):
    type: Literal['self_damage']


class AoeDamage(_ValueEffect):
    type: Literal['aoe_damage'] = Field(description="Legacy: always hits the whole enemy team.")


class Heal(_ValueEffect):
    type: Literal['heal']


class TeamHeal(_ValueEffect):
    type: Literal['team_heal']


class Defense(_ValueEffect):
    type: Literal['defense'] = Field(description="Permanent destructible defense.")


class RandomMultiDamage(_ValueEffect):
    type: Literal['random_multi_damage']
    count: int = Field(default=None, ge=1, le=6)


class _TimedValueEffect(_ValueEffect):
    duration: Turns = None


class DelayedDamage(_TimedValueEffect):
    type: Literal['delayed_damage'] = Field(description="Visible charge; unmitigated hit when it expires.")


class Dot(_TimedValueEffect):
    type: Literal['dot']


class Hot(_TimedValueEffect):
    type: Literal['hot']


class ExpiringDefense(_TimedValueEffect):
    type: Literal['expiring_defense'] = Field(description="Shield whose unused part is removed when it expires.")


class _TimedEffect(EffectBase):
    duration: Turns = None


class Protect(_TimedEffect):
    type: Literal['protect']


class HealBlock(_TimedEffect):
    type: Literal['heal_block']


class Stun(_TimedEffect):
    type: Literal['stun']


class Silence(_TimedEffect):
    type: Literal['silence']
    classes: list[SkillClass] = Field(default=None, min_length=1)


class Invulnerability(_TimedEffect):
    type: Literal['invulnerable', 'physical_invulnerable', 'chakra_invulnerable', 'mental_invulnerable']


class ReactiveDefense(_TimedEffect):
    type: Literal['dodge', 'counter', 'reflect']


class MarkForCounter(_TimedEffect):
    type: Literal['mark_for_counter'] = Field(description="Hidden trap: the target's next skill attempt is countered.")
    value: Amount = None


class Modifier(_TimedEffect):
    type: Literal['damage_taken_mod', 'damage_dealt_mod', 'heal_received_mod', 'heal_dealt_mod']
    value: Percent
    tag: Literal['buff', 'harmful'] = None


class RemoveDefense(EffectBase):
    type: Literal['remove_defense']


class Cleanse(EffectBase):
    type: Literal['cleanse']
    scope: str = Field(default=None, description="'harmful', 'buff', or a specific status type.")


class ChakraRemoval(EffectBase):
    type: Literal['remove_chakra', 'steal_chakra']
    amount: int = Field(default=None, ge=1, le=10)
    chakra_type: KiType = None


class ChakraRegen(EffectBase):
    type: Literal['chakra_regen']
    amount: int = Field(default=None, ge=1, le=10)


class ChakraRestrict(_TimedEffect):
    type: Literal['chakra_restrict']
    chakra_type: KiType = None


class ChakraDrainOverTime(_TimedEffect):
    type: Literal['chakra_drain_over_time']
    value: int = Field(default=None, ge=1, le=10)


# --- permanent stacking transformations (e.g. Kaioken) -----------------------

class _StackEffect(EffectBase):
    stack_key: str = Field(min_length=1)


class AddStack(_StackEffect):
    type: Literal['add_stack']


class SelfDamageByStack(_StackEffect):
    type: Literal['self_damage_by_stack']
    schedule: list[Amount] = Field(min_length=1, description="HP cost per use; the last value repeats.")


class _SkillStackEffect(_StackEffect):
    skill_id: str = Field(description="A skill in this same character's kit.")


class BoostSkillOnStack(_SkillStackEffect):
    type: Literal['boost_skill_on_stack']
    at_stack: int = Field(ge=1)
    bonus: int
    effect_index: int = Field(default=None, ge=0)
    new_description: str = Field(default=None, min_length=1)


class UnlockSkillOnStack(_SkillStackEffect):
    type: Literal['unlock_skill_on_stack']
    at_stack: int = Field(ge=1)


class ScaleSkillByStack(_SkillStackEffect):
    type: Literal['scale_skill_by_stack']
    base: Amount
    increment: int
    effect_index: int = Field(default=None, ge=0)
    description_template: str = Field(default=None, description="Text with a {value} placeholder.")


class SetSkillCostOnStack(_SkillStackEffect):
    type: Literal['set_skill_cost_on_stack']
    at_stack: int = Field(ge=1)
    cost: Cost
    new_description: str = Field(default=None, min_length=1)


# --- temporary, reversible skill swaps (e.g. Best Friend -> Tri-Beam) --------

class PrimeSkill(EffectBase):
    type: Literal['prime_skill']
    skill_id: str = Field(description="Skill in this kit to swap (may be this same skill).")
    mark: str = Field(min_length=1)
    duration: Turns = None
    primed_cost: Cost
    primed_effects: list['Effect'] = Field(min_length=1)
    primed_description: str = Field(default=None, min_length=1)
    primed_name: str = Field(default=None, min_length=1)
    primed_image: str = Field(default=None, min_length=1)
    primed_cooldown: int = Field(default=None, ge=0, le=20)
    primed_target_type: TargetType = None


class UnprimeSkill(EffectBase):
    type: Literal['unprime_skill']
    skill_id: str
    mark: str = None


Effect = Annotated[Union[
    Damage, PiercingDamage, AfflictionDamage, DamageIgnoreInvuln, SelfDamage, AoeDamage,
    RandomMultiDamage, DelayedDamage, Dot, Heal, Hot, TeamHeal, Protect, MarkForCounter,
    HealBlock, Stun, Silence, Defense, RemoveDefense, ExpiringDefense, Modifier,
    Invulnerability, ReactiveDefense, Cleanse, ChakraRemoval, ChakraRegen, ChakraRestrict,
    ChakraDrainOverTime, AddStack, SelfDamageByStack, BoostSkillOnStack, UnlockSkillOnStack,
    ScaleSkillByStack, SetSkillCostOnStack, PrimeSkill, UnprimeSkill,
], Field(discriminator='type')]

PrimeSkill.model_rebuild()


def effect_types():
    """Every effect `type` string the content format accepts."""
    import typing
    union = typing.get_args(Effect)[0]
    types = set()
    for model in typing.get_args(union):
        types.update(typing.get_args(model.model_fields['type'].annotation))
    return types


# --- skills & characters ------------------------------------------------------

class Skill(Strict):
    id: str = Field(pattern=r'^[a-z0-9_]+$', description="Unique within this character's kit.")
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=400)
    cost: Cost
    target_type: TargetType
    classes: list[SkillClass] = Field(default=None, min_length=1)
    image: str = Field(default=None, min_length=1, description="File in backend/photos/skills/.")
    effects: list[Effect] = Field(min_length=1)
    cooldown: int = Field(ge=0, le=20)
    locked: bool = None
    locked_reason: str = Field(default=None, min_length=1)
    notes: str = Field(default=None, description="Design notes for authors; never sent to players.")


class SharedSkillRef(Strict):
    """Uses a skill from shared_abilities.json. Only presentation can be
    changed; the mechanics stay identical roster-wide."""
    use: str = Field(description="Key in shared_abilities.json, e.g. 'afterimage_technique'.")
    name: str = Field(default=None, min_length=1, max_length=40)
    image: str = Field(default=None, min_length=1)
    notes: str = None


def _skill_kind(value):
    if isinstance(value, dict):
        return 'ref' if 'use' in value else 'skill'
    return 'ref' if hasattr(value, 'use') else 'skill'


SkillEntry = Annotated[Union[Annotated[Skill, Tag('skill')], Annotated[SharedSkillRef, Tag('ref')]],
                       Discriminator(_skill_kind)]


class Character(Strict):
    schema_: str = Field(default=None, alias='$schema')
    id: str = Field(pattern=r'^[a-z0-9_]+$', max_length=32, description="Saga-versioned, e.g. goku_saiyan_saga.")
    name: str = Field(min_length=1, max_length=64)
    image: str = Field(min_length=1, description="Path under backend/photos/, e.g. characters/Goku.png.")
    health: int = Field(ge=1, le=999)
    notes: str = None
    skills: list[SkillEntry] = Field(min_length=1, max_length=8)


class SharedAbilities(Strict):
    schema_: str = Field(default=None, alias='$schema')
    abilities: dict[str, Skill]


# --- JSON Schema generation (editor support) ---------------------------------

SCHEMA_FILES = {
    'character.schema.json': Character,
    'shared_abilities.schema.json': SharedAbilities,
}


def build_schemas():
    return {name: model.model_json_schema(by_alias=True) for name, model in SCHEMA_FILES.items()}


def write_schemas():
    for name, schema in build_schemas().items():
        with open(os.path.join(CONTENT_DIR, name), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(schema, fh, indent=2, ensure_ascii=False)
            fh.write('\n')


if __name__ == '__main__':
    write_schemas()
    print(f"Wrote {', '.join(SCHEMA_FILES)} to {CONTENT_DIR}")
