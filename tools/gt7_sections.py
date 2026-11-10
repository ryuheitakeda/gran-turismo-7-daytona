#!/usr/bin/env python3
"""Read the GT7 section-time table (shown by pressing right on the D-pad twice during a race)
from screenshots and write one JSON line per lap.

usage: gt7_sections.py [--out FILE] [--step N] [--race N] FRAME_DIR_OR_PNG...
needs: Pillow and the `tesseract` command. Frames are Chiaki screenshots (any size, 16:9).
The three section times are checked against LAST (their sum must match exactly);
rows that fail are skipped (a lap read twice a few ms apart counts once), so a misread number never reaches the output.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

# the table, as fractions of the frame (measured on 1280x720)
BOX = (565 / 1280, 572 / 720, 745 / 1280, 695 / 720)
TIME = re.compile(r"(\d)'(\d\d)\.(\d\d\d)")


def to_ms(m, s, ms):
    return int(m) * 60000 + int(s) * 1000 + int(ms)


def parse_table(text):
    """OCR text of the table -> (sections_ms [s1, s2, s3], last_ms), or None if it doesn't add up.

    The rows come top to bottom as sections 3, 2, 1, then LAST, BEST and OPT, and each
    line starts with its own time (the delta after it is too noisy to read)."""
    times = []
    for line in text.splitlines():
        m = TIME.search(line.replace(' ', ''))
        if m:
            times.append(to_ms(*m.groups()))
    if len(times) < 4:
        return None
    s3, s2, s1, last = times[:4]
    if s1 + s2 + s3 != last:
        return None
    return [s1, s2, s3], last


def ocr(png_path):
    from PIL import Image
    im = Image.open(png_path).convert('L')
    w, h = im.size
    box = (int(BOX[0] * w), int(BOX[1] * h), int(BOX[2] * w), int(BOX[3] * h))
    c = im.crop(box)
    c = c.resize((c.width * 4 * 1280 // w, c.height * 4 * 1280 // w))
    with tempfile.TemporaryDirectory() as d:
        tmp = os.path.join(d, 'crop.png')
        c.save(tmp)
        r = subprocess.run(['tesseract', tmp, '-', '--psm', '6', '-c', "tessedit_char_whitelist=0123456789'.-"],
                           capture_output=True, text=True,
                           env=dict(os.environ, OMP_THREAD_LIMIT='1'))  # one thread: it runs next to the farm
    return r.stdout


def frames(paths, step=1, race=None):
    """Every `step`th frame; with `race`, only the race screenshots of that race
    (names like 232052.0-race3-race.png).  The full table is on screen only ~15 s after a
    lap ends and the blurry video drops some digits, so about half of the laps are read;
    a smaller step reads more."""
    for p in paths:
        if os.path.isdir(p):
            found = sorted(glob.glob(os.path.join(p, '*.png')))
            if race is not None:
                found = [f for f in found if f.endswith('-race%d-race.png' % race)]
            yield from found[::step]
        else:
            yield p


def run(paths, out, step=1, race=None):
    seen = None
    n = 0
    for f in frames(paths, step, race):
        parsed = parse_table(ocr(f))
        if not parsed or (seen is not None and abs(parsed[1] - seen) <= 5):
            continue  # unreadable, or the same lap as the last row
        sections, last = parsed
        seen = last
        m = re.search(r'-race(\d+)-', os.path.basename(f))
        row = {'kind': 'sections', 'race': int(m.group(1)) if m else None, 'frame': os.path.basename(f), 'sections_ms': sections, 'lap_ms': last}
        out.write(json.dumps(row, separators=(',', ':')) + '\n')
        out.flush()
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', help='append to this file (default: stdout)')
    ap.add_argument('--step', type=int, default=1, help='read every Nth frame of a folder')
    ap.add_argument('--race', type=int, help='only the race screenshots of this race number')
    ap.add_argument('paths', nargs='+')
    a = ap.parse_args()
    out = open(a.out, 'a', encoding='utf-8') if a.out else sys.stdout
    n = run(a.paths, out, a.step, a.race)
    print('%d laps' % n, file=sys.stderr)


if __name__ == '__main__':
    main()
