# Capture the Chiaki stream window, save it as PNG and tell which GT7 screen it
# shows, with nothing but xwd (x11-apps) and python3's standard library. xwd
# doesn't grab the X server.
#
# A screen is told by parts of the picture that don't move (titles, buttons,
# hints): their bright pixels (the white text), taken every other pixel, are
# compared with references learned from screenshots of this machine
# (gt7-screen.py learn). Only the text counts, so the moving 3D background
# behind some titles doesn't. The references stay out of the repository: they
# are pictures of the game.

import json
import os
import struct
import subprocess
import zlib

WINDOW_NAME = os.environ.get('WINDOW_NAME', r'^Chiaki \| Stream$')
REFERENCES = os.environ.get('SCREEN_REFERENCES',
                            os.path.expanduser('~/.config/gt7-daytona/screens'))
WIDTH, HEIGHT = 1280, 720  # the regions below are for this size

# name: regions (x, y, width, height[, brightness]) that only this screen has, as seen on
# GT7 in 2026-10; brightness is the grey above which a pixel counts as text (default BRIGHT)
SCREENS = {
    'start': [(20, 62, 140, 46), (480, 530, 320, 30)],  # title, laps and start type
    'start-idle': [(20, 4, 300, 46)],  # the menu screens' top bar: the start screen after its menu hid
    'finish': [(575, 310, 130, 100, 215), (600, 676, 80, 28)],  # "1st" (white, not the yellow line), "x next"
    'standings': [(485, 30, 330, 72), (600, 676, 80, 28)],  # logo and title, "x next"
    'rewards': [(100, 318, 290, 58), (600, 658, 80, 28)],  # REWARDS, "x next"
    'replay': [(1060, 636, 200, 60, 95)],  # GRAN TURISMO 7 in the corner (faint), without the replay bar
    'replay-menu': [(40, 628, 170, 80), (1165, 640, 85, 56)],  # hints, Exit lit
    'result': [(140, 92, 300, 32)],  # RACE RESULT
    'result-menu': [(385, 550, 220, 150)],  # the Replay button's menu, over the race result
    'race': [(85, 28, 70, 20), (195, 28, 35, 20)],  # POSITION and LAP over the race
}
# the buttons of a screen: the rows to look at, and each button's x range; the one the
# cursor is on is white there (an edge on the start and result screens, the whole
# button on the pause menu)
BUTTONS = {
    'start': (640, 650, {'start': (225, 375), 'replay': (425, 575), 'settings': (625, 775),
                         'options': (820, 870), 'shop': (915, 965), 'exit': (1005, 1060)}),
    'result': (640, 650, {'replay': (420, 565), 'retry': (620, 765), 'exit': (815, 865)}),
    'pause': (345, 352, {'continue': (240, 432), 'retry': (442, 635), 'settings': (645, 838),
                         'exit': (848, 1040)}),
}
LIT = 170  # grey of a lit button (about 215-225); unlit ones are 45-110
# the pause menu is the race with a bar of four buttons over it: between that many text
# pixels there (a white flash has them all), one button white and the other three dark
PAUSE_BAR = (235, 340, 810, 40)
PAUSE_TEXT = (1500, 2500)  # measured 1920 and 1983
PAUSE_LIT = (200, 245)  # the white button, measured 221 and 224
PAUSE_DARK = (60, 125)  # the three grey ones, measured 79 to 107
BRIGHT = 160  # grey above which a pixel counts as text
MATCH = 20  # percent of the text pixels that may differ for a screen to count as seen


def find_window(name=WINDOW_NAME):
    out = subprocess.run(['xdotool', 'search', '--name', name], capture_output=True, text=True).stdout
    if not out.split():
        raise RuntimeError('no window matches %r' % name)
    return int(out.split()[0])


def capture(window):
    """The window's image now, as (width, height, RGB bytes)."""
    data = subprocess.run(['xwd', '-silent', '-id', str(window)], capture_output=True,
                          check=True, timeout=10).stdout
    h = struct.unpack_from('>25I', data, 0)  # XWDFileHeader, always big-endian
    header_size, version, pixmap_format, width, height = h[0], h[1], h[2], h[4], h[5]
    byte_order, bits_per_pixel, bytes_per_line, ncolors = h[7], h[11], h[12], h[19]
    masks = h[14:17] if all(h[14:17]) else (0xff0000, 0xff00, 0xff)
    # 32 bits a pixel, or 24 when the window has a visual of its own (Chiaki's stream
    # window opened with `chiaki stream`)
    if version != 7 or pixmap_format != 2 or bits_per_pixel not in (24, 32):
        raise RuntimeError('unsupported xwd image (version %d, format %d, %d bpp)'
                           % (version, pixmap_format, bits_per_pixel))
    n = bits_per_pixel // 8
    start = header_size + ncolors * 12
    pixels = data[start:start + bytes_per_line * height]
    if bytes_per_line != width * n:
        pixels = b''.join(pixels[y * bytes_per_line:y * bytes_per_line + width * n]
                          for y in range(height))
    # each colour's byte in a pixel, from its mask: BGR(X) or (X)RGB in memory
    r, g, b = ((m.bit_length() - 8) // 8 if byte_order == 0 else n - 1 - (m.bit_length() - 8) // 8
               for m in masks)
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = pixels[r::n], pixels[g::n], pixels[b::n]
    return width, height, bytes(rgb)


def png(width, height, rgb):
    stride = width * 3
    raw = b''.join(b'\0' + rgb[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def save_png(path, width, height, rgb):
    with open(path + '.tmp', 'wb') as f:
        f.write(png(width, height, rgb))
    os.replace(path + '.tmp', path)


def load_png(path):
    """(width, height, RGB bytes) of a PNG saved by save_png (8-bit RGB, no filters)."""
    data = open(path, 'rb').read()
    width, height = struct.unpack('>II', data[16:24])
    idat, pos = b'', 8
    while pos < len(data):
        size, kind = struct.unpack('>I4s', data[pos:pos + 8])
        if kind == b'IDAT':
            idat += data[pos + 8:pos + 8 + size]
        pos += 12 + size
    raw = zlib.decompress(idat)
    stride = width * 3 + 1
    return width, height, b''.join(raw[y * stride + 1:(y + 1) * stride] for y in range(height))


def grey(image, region, step=4):
    """The region of a (width, height, RGB) image, every step-th pixel, in grey."""
    width, height, rgb = image
    x, y, w, h = region
    out = []
    for row in range(y, min(y + h, height), step):
        line = rgb[(row * width + x) * 3:(row * width + min(x + w, width)) * 3]
        out += [(r * 299 + g * 587 + b * 114) // 1000
                for r, g, b in zip(line[0::3 * step], line[1::3 * step], line[2::3 * step])]
    return out


def text(image, region):
    """The region's pixels as 1 (bright: text) or 0, every other pixel."""
    bright = region[4] if len(region) > 4 else BRIGHT
    return [int(v > bright) for v in grey(image, region[:4], 2)]


def learn(name, image, directory=REFERENCES):
    if image[0] != WIDTH or image[1] != HEIGHT:
        raise ValueError('the screenshot is %dx%d, not %dx%d' % (image[0], image[1], WIDTH, HEIGHT))
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, name + '.json'), 'w') as f:
        json.dump([text(image, region) for region in SCREENS[name]], f)


def references(directory=REFERENCES):
    refs = {}
    for name in SCREENS:
        try:
            refs[name] = json.load(open(os.path.join(directory, name + '.json')))
        except OSError:
            pass
    return refs


def distances(image, refs):
    """For each learned screen, the percent of text pixels that differ, smallest first.
    Pixels dark in both don't count; with no text on either side nothing matches."""
    out = []
    for name, ref in refs.items():
        differ = lit = 0
        for region, expected in zip(SCREENS[name], ref):
            for a, b in zip(text(image, region), expected):
                differ += a != b
                lit += a or b
        out.append((100 * differ / lit if lit else 100.0, name))
    return sorted(out)


def button_greys(image, buttons):
    """Each button's brightest row (mean grey). buttons is BUTTONS[screen]."""
    y0, y1, ranges = buttons
    return {name: max(sum(v) / len(v) for v in (grey(image, (x0, y, x1 - x0, 1), 2) for y in range(y0, y1)))
            for name, (x0, x1) in ranges.items()}


def lit_button(image, buttons):
    """The button the cursor is on (white), or None."""
    for name, value in button_greys(image, buttons).items():
        if value > LIT:
            return name
    return None


def pause_menu(image):
    """'continue', 'retry', 'settings' or 'exit' when the pause menu shows with the cursor
    there, else None."""
    if not PAUSE_TEXT[0] <= sum(text(image, PAUSE_BAR)) <= PAUSE_TEXT[1]:
        return None
    greys = button_greys(image, BUTTONS['pause'])
    lit = [name for name, v in greys.items() if PAUSE_LIT[0] <= v <= PAUSE_LIT[1]]
    dark = [name for name, v in greys.items() if PAUSE_DARK[0] <= v <= PAUSE_DARK[1]]
    return lit[0] if len(lit) == 1 and len(dark) == 3 else None


def classify(image, refs):
    """The screen the image shows, with the distance: e.g. 'rewards', 'result/retry'
    (the race result with the cursor on Retry), 'result/menu' (the Replay menu is
    open), 'start/start', 'start-idle' (its menu hid), 'pause/continue' (the race
    paused, cursor on Continue) or 'unknown'."""
    if image[0] != WIDTH or image[1] != HEIGHT:
        return 'unknown', 255.0
    # the pause menu dims the race under it, so look for its bar first
    lit = pause_menu(image)
    if lit:
        return 'pause/' + lit, 0.0
    best = distances(image, {k: v for k, v in refs.items() if k not in ('result-menu', 'start-idle')})
    if not best or best[0][0] >= MATCH:
        # nothing else, but the top bar of the menus: the start screen after its menu hid
        if 'start-idle' in refs and distances(image, {'start-idle': refs['start-idle']})[0][0] < MATCH:
            return 'start-idle', distances(image, {'start-idle': refs['start-idle']})[0][0]
        return 'unknown', best[0][0] if best else 255.0
    distance, name = best[0]
    if name == 'result' and 'result-menu' in refs and \
            distances(image, {'result-menu': refs['result-menu']})[0][0] < MATCH:
        return 'result/menu', distance
    if name in BUTTONS:
        return '%s/%s' % (name, lit_button(image, BUTTONS[name]) or '?'), distance
    return name, distance


# where the credits show: the top bar of the menus, and the balance on the rewards screen
TOP_CREDITS = (352, 24, 115, 24)
REWARD_BALANCE = (950, 278, 200, 38)


def read_number(image, region, bright=150, scale=3):
    """The number in a region of white digits, read by tesseract (tesseract-ocr), or
    None without tesseract or when nothing like a number is there."""
    width, height, rgb = image
    x0, y0, w, h = region
    out = bytearray()
    for y in range(y0, y0 + h):
        row = rgb[(y * width + x0) * 3:(y * width + x0 + w) * 3]
        line = bytearray()
        for r, g, b in zip(row[0::3], row[1::3], row[2::3]):
            line += bytes([0 if (r * 299 + g * 587 + b * 114) // 1000 > bright else 255]) * scale
        out += bytes(line) * scale
    pgm = b'P5 %d %d 255\n' % (w * scale, h * scale) + bytes(out)
    try:
        result = subprocess.run(['tesseract', 'stdin', 'stdout', '--psm', '7',
                                 '-c', 'tessedit_char_whitelist=0123456789,'],
                                input=pgm, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    digits = result.stdout.decode(errors='replace').strip().replace(',', '')
    return int(digits) if digits.isdigit() else None
