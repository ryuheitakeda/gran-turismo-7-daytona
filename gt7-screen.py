#!/usr/bin/env python3

# Save screenshots of the Chiaki stream window
# Usage: gt7-screen.py snap [--id <window>] <file.png>
#        gt7-screen.py record [--id <window>] --every <seconds> <dir> <label>
#   record saves <dir>/<HHMMSS.s>-<label>.png every <seconds> until it is stopped.
#   Without --id the window is found by WINDOW_NAME (default '^Chiaki \| Stream$').

import argparse
import datetime
import os
import signal
import subprocess
import sys
import time

from gt7 import screen


def main():
    parser = argparse.ArgumentParser(description='Save screenshots of the Chiaki stream window')
    parser.add_argument('command', choices=['snap', 'record'])
    parser.add_argument('--id', type=lambda s: int(s, 0), help='window id (default: find by WINDOW_NAME)')
    parser.add_argument('--every', type=float, default=1, help='record: seconds between screenshots')
    parser.add_argument('path', help='snap: PNG file; record: directory')
    parser.add_argument('label', nargs='?', default='screen', help='record: added to the file names')
    args = parser.parse_args()
    window = args.id or screen.find_window()
    if args.command == 'snap':
        screen.save_png(args.path, *screen.capture(window))
        return
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    while True:
        started = time.time()
        stamp = datetime.datetime.now().strftime('%H%M%S.%f')[:8]
        try:
            screen.save_png(os.path.join(args.path, '%s-%s.png' % (stamp, args.label)),
                            *screen.capture(window))
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:
            print('screenshot failed: %s' % e, file=sys.stderr, flush=True)
        time.sleep(max(0, args.every - (time.time() - started)))


main()
