"""
Loads and validates game content from backend/content/:

  content/shared_abilities.json         skills shared roster-wide (e.g. the universal afterimage_technique)
  content/characters/<character_id>.json  one file per character, its kit inside

load_catalog() returns {character_id: character_dict} in exactly the shape
the engine and app already use (runtime fields like currentCooldown/maxHealth
filled in, author-only fields like "notes" removed). Any problem -- bad JSON,
wrong shape, unknown effect, missing image, dangling skill reference -- is
collected and raised together as ContentError, so broken content stops the
server at startup instead of failing mid-match.

Validation only: no combat logic here (that stays in game_engine.py).
"""
import json
import os

from pydantic import ValidationError

import content_schema as cs

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTOS_DIR = os.path.join(BACKEND_DIR, 'photos')

# Web-ready art (AST-1; tools/optimize_images.py makes it so). Sizes: the game shows portraits at most 220 px wide and
# skill icons at 32 px; the boxes leave room for high-resolution screens.
IMAGE_BOX = {'portrait': (480, 480), 'icon': (96, 96)}
WEBP_QUALITY = 82
IMAGE_MAX_BYTES = {'portrait': 80 * 1024, 'icon': 16 * 1024}
FIX_IMAGES = "run: python tools/optimize_images.py"


def image_type(path):
    """'WEBP' / 'PNG' / 'JPEG' from the file's first bytes, or None."""
    with open(path, 'rb') as fh:
        head = fh.read(12)
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'WEBP'
    if head[:8] == b'\x89PNG\r\n\x1a\n':
        return 'PNG'
    if head[:3] == b'\xff\xd8\xff':
        return 'JPEG'
    return None


def check_image(label, relative, kind, photos_dir, problems):
    """An image a content file names: it exists, is what its name says, and is web-sized."""
    path = os.path.join(photos_dir, relative)
    if not os.path.isfile(path):
        problems.append(f"{label} not found: photos/{relative}")
        return
    real = image_type(path)
    named = {'.webp': 'WEBP', '.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG'}.get(os.path.splitext(relative)[1].lower())
    if real is None:
        problems.append(f"{label} is not an image (WebP, PNG or JPEG): photos/{relative}")
    elif real != named:
        problems.append(f"{label} is a {real} file named {os.path.splitext(relative)[1]}: photos/{relative} ({FIX_IMAGES})")
    size = os.path.getsize(path)
    if size > IMAGE_MAX_BYTES[kind]:
        problems.append(f"{label} is too large for a {kind} ({size // 1024} KB, at most {IMAGE_MAX_BYTES[kind] // 1024} KB): "
                        f"photos/{relative} ({FIX_IMAGES})")
UNIVERSAL_SKILL = 'afterimage_technique'
AUTHOR_ONLY_FIELDS = {'notes', 'schema_'}


class ContentError(Exception):
    def __init__(self, problems):
        self.problems = problems
        super().__init__(f"{len(problems)} content problem(s):\n  - " + "\n  - ".join(problems))


def _format_loc(loc):
    """('skills', 1, 'skill', 'effects', 5, 'stun', 'duration') -> 'skills[1].effects[5] (stun).duration'.
    Pydantic adds union tags (skill/ref, the effect type) to locations; show
    the effect type as a hint and drop the rest."""
    out = ''
    effect_types = cs.effect_types()
    for part in loc:
        if isinstance(part, int):
            out += f'[{part}]'
        elif part in ('skill', 'ref'):
            continue
        elif part in effect_types:
            out += f' ({part})'
        else:
            out += f'.{part}' if out else str(part)
    return out


def _validation_problems(where, err):
    return [f"{where}: {_format_loc(e['loc']) or '(root)'}: {e['msg']}" for e in err.errors()]


def _read_json(path, problems):
    where = os.path.relpath(path, BACKEND_DIR)
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        problems.append(f"{where}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}")
    except OSError as e:
        problems.append(f"{where}: can't read file: {e}")
    return None


def _dump_skill(skill_model):
    data = skill_model.model_dump(exclude_unset=True, exclude=AUTHOR_ONLY_FIELDS)
    data['currentCooldown'] = 0  # runtime state, never authored
    return data


def _walk_effects(effects):
    """Yields every effect, including those nested inside prime_skill."""
    for effect in effects:
        yield effect
        yield from _walk_effects(effect.get('primed_effects', []))


def _check_kit(where, skills, photos_dir, problems):
    """Cross-reference checks that the per-field models can't express."""
    by_id = {}
    for s in skills:
        if s['id'] in by_id:
            problems.append(f"{where}: duplicate skill id '{s['id']}' in this kit")
        by_id[s['id']] = s

    added_stacks = {e['stack_key'] for s in skills for e in _walk_effects(s['effects']) if e['type'] == 'add_stack'}
    prime_marks = {e['mark'] for s in skills for e in _walk_effects(s['effects']) if e['type'] == 'prime_skill'}
    unlocked = {e['skill_id'] for s in skills for e in _walk_effects(s['effects'])
                if e['type'] == 'unlock_skill_on_stack'}

    for s in skills:
        sw = f"{where}: skill '{s['id']}'"
        if s.get('image'):
            check_image(f"{sw}: image", 'skills/' + s['image'], 'icon', photos_dir, problems)
        if s.get('locked') and s['id'] not in unlocked:
            problems.append(f"{sw}: is locked but nothing in the kit unlocks it")
        for e in _walk_effects(s['effects']):
            ew = f"{sw}: effect '{e['type']}'"
            if 'skill_id' in e and e['skill_id'] not in by_id:
                problems.append(f"{ew}: skill_id '{e['skill_id']}' is not in this kit")
            elif 'effect_index' in e and e['effect_index'] >= len(by_id[e['skill_id']]['effects']):
                problems.append(f"{ew}: effect_index {e['effect_index']} is out of range for '{e['skill_id']}'")
            if 'stack_key' in e and e['type'] != 'add_stack' and e['stack_key'] not in added_stacks:
                problems.append(f"{ew}: stack_key '{e['stack_key']}' is never added by an add_stack effect")
            if e['type'] == 'unprime_skill' and e.get('mark') and e['mark'] not in prime_marks:
                problems.append(f"{ew}: mark '{e['mark']}' doesn't match any prime_skill mark in this kit")
            if 'description_template' in e:
                try:
                    e['description_template'].format(value=0)
                except (KeyError, IndexError, ValueError) as err:
                    problems.append(f"{ew}: description_template must only use {{value}} ({err!r})")
            if e.get('primed_image'):
                check_image(f"{ew}: primed_image", 'skills/' + e['primed_image'], 'icon', photos_dir, problems)


def load_catalog(content_dir=cs.CONTENT_DIR, photos_dir=PHOTOS_DIR):
    problems = []

    shared = {}
    shared_raw = _read_json(os.path.join(content_dir, 'shared_abilities.json'), problems)
    if shared_raw is not None:
        try:
            shared = cs.SharedAbilities.model_validate(shared_raw).abilities
        except ValidationError as e:
            problems += _validation_problems('content/shared_abilities.json', e)
        for key, skill in shared.items():
            if skill.id != key:
                problems.append(f"content/shared_abilities.json: key '{key}' must equal its skill id '{skill.id}'")

    chars_dir = os.path.join(content_dir, 'characters')
    files = sorted(f for f in os.listdir(chars_dir) if f.endswith('.json')) if os.path.isdir(chars_dir) else []
    if not files:
        problems.append("content/characters/: no character files found")

    catalog = {}
    for fname in files:
        where = f"content/characters/{fname}"
        raw = _read_json(os.path.join(chars_dir, fname), problems)
        if raw is None:
            continue
        try:
            char = cs.Character.model_validate(raw)
        except ValidationError as e:
            problems += _validation_problems(where, e)
            continue
        if fname != f"{char.id}.json":
            problems.append(f"{where}: file name must be '{char.id}.json' (the character id)")
        if char.id in catalog:
            problems.append(f"{where}: duplicate character id '{char.id}'")
        check_image(f"{where}: image", char.image, 'portrait', photos_dir, problems)

        skills, universal = [], 0
        for i, entry in enumerate(char.skills):
            if isinstance(entry, cs.SharedSkillRef):
                if entry.use not in shared:
                    problems.append(f"{where}: skills[{i}]: unknown shared ability '{entry.use}'")
                    continue
                skill = _dump_skill(shared[entry.use])
                skill.update(entry.model_dump(exclude_unset=True, exclude={'use', 'notes'}))
                universal += entry.use == UNIVERSAL_SKILL
            else:
                skill = _dump_skill(entry)
            skills.append(skill)
        if universal != 1:
            problems.append(f"{where}: must use the shared '{UNIVERSAL_SKILL}' skill exactly once (found {universal})")
        _check_kit(where, skills, photos_dir, problems)

        catalog[char.id] = {
            'id': char.id, 'name': char.name, 'image': char.image,
            'health': char.health, 'maxHealth': char.health, 'status': [],
            'skills': skills,
        }

    if problems:
        raise ContentError(problems)
    return catalog


_CATALOG = None


def catalog():
    """The validated roster, loaded once per process and shared read-only.
    Callers that modify a character (teams, image URLs) must deep-copy it."""
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = load_catalog()
    return _CATALOG
