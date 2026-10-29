#!/usr/bin/env python3

# Check and try out the virtual gamepad (gt7/pad.py)
# Usage: gt7-pad.py check                      make the pad, check that Chiaki opened it, remove it
#        gt7-pad.py press <button> [seconds]   press a button once
#        gt7-pad.py hold <button>              hold it until stopped (kill -9 must let go too)
#   buttons: cross circle square triangle l1 r1 share options l3 r3 up down left right
# Only press anything while the script is not racing: Chiaki sends it to the game.

import sys
import time

from gt7 import pad

USAGE = 'Usage: gt7-pad.py check | press <button> [seconds] | hold <button>'


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ('check', 'press', 'hold') or (args[0] != 'check' and len(args) < 2):
        sys.exit(USAGE)
    if args[0] != 'check' and args[1] not in pad.BUTTONS and args[1] not in pad.DPAD:
        sys.exit('Unknown button %r. %s' % (args[1], USAGE))
    try:
        p = pad.Pad()
    except OSError as e:
        sys.exit('Cannot make the pad: %s (is /dev/uinput writable?)' % e)
    try:
        device = p.device()
        deadline = time.time() + 5
        while not pad.opened_by(device):
            if time.time() > deadline:
                sys.exit('Chiaki did not open the pad %s. Is 70-gt7-pad.rules installed '
                         'and is Chiaki streaming?' % device)
            time.sleep(0.1)
        print('Chiaki opened the pad %s' % device, flush=True)
        if args[0] == 'press':
            p.press(args[1], float(args[2]) if len(args) > 2 else 0.08)
            time.sleep(0.3)
        elif args[0] == 'hold':
            p.button(args[1], True)
            print('Holding %s; stop with CTRL+C or kill' % args[1], flush=True)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        p.close()


main()
