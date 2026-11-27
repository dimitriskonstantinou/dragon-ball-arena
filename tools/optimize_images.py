"""
Makes the art the game uses web-ready (AST-1): every image referenced by backend/content/ becomes a real WebP file
at the size the game shows it (a bit larger for high-resolution screens), and the character files point to it.
Run after adding or replacing art, from the repo root:

    python tools/optimize_images.py            # converts and rewrites the references; prints before/after
    python tools/optimize_images.py --dry-run  # only shows what it would do

Needs Pillow (pip install pillow; only for this tool). The originals stay in git history. The server refuses to
start with an image of the wrong type or above the size limit (content_loader), so a new image is never forgotten.
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, 'backend', 'content')
PHOTOS = os.path.join(ROOT, 'backend', 'photos')
sys.path.insert(0, os.path.join(ROOT, 'backend'))
from content_loader import IMAGE_BOX, WEBP_QUALITY  # noqa: E402  (one source of truth for the limits)


def referenced_images():
    """{photos-relative path: kind} for every image the content files name ('characters/x' or 'skills/x')."""
    found = {}
    for folder in ('characters', ''):
        base = os.path.join(CONTENT, folder)
        for name in sorted(os.listdir(base)):
            if not name.endswith('.json') or name.endswith('.schema.json'):
                continue
            text = open(os.path.join(base, name), encoding='utf-8').read()
            for key, value in re.findall(r'"(image|primed_image)"\s*:\s*"([^"]+)"', text):
                path = value if value.startswith('characters/') else 'skills/' + value
                found[path] = 'portrait' if path.startswith('characters/') else 'icon'
    return found


def convert(path, kind, dry_run):
    from PIL import Image
    source = os.path.join(PHOTOS, path)
    target_rel = os.path.splitext(path)[0] + '.webp'
    target = os.path.join(PHOTOS, target_rel)
    before = os.path.getsize(source)
    with Image.open(source) as im:
        size, fmt = im.size, im.format
        im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
        im.thumbnail(IMAGE_BOX[kind], Image.LANCZOS)   # keeps the shape; never enlarges
        if dry_run:
            return target_rel, before, None, fmt, size, im.size
        tmp = target + '.tmp'
        im.save(tmp, 'WEBP', quality=WEBP_QUALITY, method=6)
    os.replace(tmp, target)
    if os.path.normcase(source) != os.path.normcase(target):
        os.remove(source)
    return target_rel, before, os.path.getsize(target), fmt, size, im.size


def rewrite_references(renames):
    for folder in ('characters', ''):
        base = os.path.join(CONTENT, folder)
        for name in sorted(os.listdir(base)):
            if not name.endswith('.json') or name.endswith('.schema.json'):
                continue
            file = os.path.join(base, name)
            text = original = open(file, encoding='utf-8', newline='').read()
            for old, new in renames.items():
                short_old, short_new = (old, new) if old.startswith('characters/') else (old[7:], new[7:])
                text = re.sub(r'("(?:image|primed_image)"\s*:\s*")' + re.escape(short_old) + '"',
                              lambda m: m.group(1) + short_new + '"', text)
            if text != original:
                open(file, 'w', encoding='utf-8', newline='').write(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    renames, total_before, total_after = {}, 0, 0
    for path, kind in referenced_images().items():
        target, before, after, fmt, old_size, new_size = convert(path, kind, args.dry_run)
        total_before += before
        total_after += after or 0
        if target != path:
            renames[path] = target
        print(f"{path:55s} {fmt:4s} {old_size[0]}x{old_size[1]} {before // 1024:4d} KB -> {target} "
              f"{new_size[0]}x{new_size[1]}" + (f" {after // 1024} KB" if after else ''))
    if not args.dry_run:
        rewrite_references(renames)
        print(f"\n{len(renames)} renamed; {total_before / 1024:.0f} KB -> {total_after / 1024:.0f} KB")


if __name__ == '__main__':
    main()
