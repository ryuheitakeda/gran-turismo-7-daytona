#!/usr/bin/env python3

# Screenshots of the Chiaki stream window, and which GT7 screen they show
# Usage: gt7-screen.py snap [--id <window>] <file.png>
#        gt7-screen.py record [--id <window>] --every <seconds> <dir> <label>
#        gt7-screen.py learn <screen> <file.png>
#        gt7-screen.py classify [<file.png or dir> ...]
#        gt7-screen.py wait [--id <window>] <screen>[,<screen>...] <seconds>
#        gt7-screen.py to-start [--id <window>] [--keys <cross>,<circle>,<left>,<right>] [--check]
#   record saves <dir>/<HHMMSS.s>-<label>.png every <seconds> until it is stopped.
#   learn keeps the screen's parts of a screenshot as the reference for it.
#   classify prints the screen each picture (or the window now) shows.
#   wait exits 0 when one of the screens shows, 1 after the seconds.
#   to-start presses through the screens after a race (with xdotool, Chiaki's default
#   keys unless --keys) until the start screen shows: exit 0 there, 1 if it doesn't
#   get there, 2 (or with --check, 0) depending on whether the references it needs
#   have been learned.
#   Without --id the window is found by WINDOW_NAME (default '^Chiaki \| Stream$').

import argparse
import datetime
import os
import signal
import subprocess
import sys
import time

from gt7 import menus, screen

NEEDED = ('start', 'standings', 'rewards', 'replay', 'replay-menu', 'result', 'result-menu')


def window(args):
    return args.id or screen.find_window()


def main():
    parser = argparse.ArgumentParser(description='Screenshots of the Chiaki stream window')
    parser.add_argument('command', choices=['snap', 'record', 'learn', 'classify', 'wait', 'to-start'])
    parser.add_argument('--id', type=lambda s: int(s, 0), help='window id (default: find by WINDOW_NAME)')
    parser.add_argument('--every', type=float, default=1, help='record: seconds between screenshots')
    parser.add_argument('--keys', default='Return,BackSpace,Left,Right',
                        help='to-start: xdotool keys for cross, circle, left and right')
    parser.add_argument('--check', action='store_true', help='to-start: only check the references')
    parser.add_argument('args', nargs='*')
    args = parser.parse_args()
    a = args.args

    if args.command == 'snap' and len(a) == 1:
        screen.save_png(a[0], *screen.capture(window(args)))
    elif args.command == 'record' and len(a) == 2:
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        win = window(args)
        while True:
            started = time.time()
            stamp = datetime.datetime.now().strftime('%H%M%S.%f')[:8]
            try:
                screen.save_png(os.path.join(a[0], '%s-%s.png' % (stamp, a[1])), *screen.capture(win))
            except (OSError, RuntimeError, subprocess.SubprocessError) as e:
                print('screenshot failed: %s' % e, file=sys.stderr, flush=True)
            time.sleep(max(0, args.every - (time.time() - started)))
    elif args.command == 'learn' and len(a) == 2 and a[0] in screen.SCREENS:
        screen.learn(a[0], screen.load_png(a[1]))
        print('learned %s from %s' % (a[0], a[1]))
    elif args.command == 'classify':
        refs = screen.references()
        if not refs:
            sys.exit('No references in %s yet: gt7-screen.py learn <screen> <file.png>' % screen.REFERENCES)
        files = []
        for path in a:
            files += sorted(os.path.join(path, f) for f in os.listdir(path) if f.endswith('.png')) \
                if os.path.isdir(path) else [path]
        for path in files or [None]:
            image = screen.load_png(path) if path else screen.capture(window(args))
            ranked = screen.distances(image, refs)
            name, distance = screen.classify(image, refs)
            print('%-40s %-15s %5.1f   (next: %s %.1f)' % (
                os.path.basename(path) if path else 'now', name, distance,
                ranked[1][1] if len(ranked) > 1 else '-', ranked[1][0] if len(ranked) > 1 else 0))
    elif args.command == 'wait' and len(a) == 2:
        wanted, deadline = a[0].split(','), time.time() + float(a[1])
        refs, win, name = screen.references(), window(args), 'unknown'
        while time.time() < deadline:
            name, _ = screen.classify(screen.capture(win), refs)
            if name in wanted:
                print(name)
                return
            time.sleep(0.3)
        print(name)
        sys.exit(1)
    elif args.command == 'to-start' and not a:
        refs = screen.references()
        missing = [name for name in NEEDED if name not in refs]
        if missing or args.check:
            if missing:
                print('Not learned yet: %s' % ' '.join(missing), file=sys.stderr)
            sys.exit(2 if missing else 0)
        win = window(args)
        keys = dict(zip(('cross', 'circle', 'left', 'right'), args.keys.split(',')))

        def press(button):
            subprocess.run(['xdotool', 'keydown', '--window', str(win), keys[button], 'sleep', '0.08',
                            'keyup', '--window', str(win), keys[button]], check=True)

        def log(text):
            print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + text, flush=True)
        if not menus.to_start(press, lambda: screen.classify(screen.capture(win), refs)[0], log):
            sys.exit(1)
    else:
        parser.print_usage(sys.stderr)
        sys.exit(2)


main()
