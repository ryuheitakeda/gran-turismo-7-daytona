# Go from the end of a race back to the start screen by looking at the screen
# before every press, instead of pressing on a timer (gt7/screen.py tells the
# screens apart). Works with any way of pressing: keys or the virtual pad.

import time

# what to press on each screen to get closer to the start screen
NEXT = {
    'finish': 'cross',  # "1st" after the finish line: skip it
    'standings': 'cross',
    'rewards': 'cross',  # the credits, then the miles, then on to the replay
    'replay': 'cross',  # shows the replay's menu, with the cursor on Exit
    'replay-menu': 'cross',  # Exit
    'result/replay': 'right',
    'result/exit': 'left',
    'result/retry': 'cross',
    'result/menu': 'circle',  # close the Replay button's menu
    'start/replay': 'left',
    'start/settings': 'left',
    'start/options': 'left',
    'start/shop': 'left',
    'start/exit': 'left',
}
STEPS = {'standings': 'Standings', 'rewards': 'Rewards', 'replay': 'Replay', 'result/retry': 'Retry'}


def to_start(press, look, log=lambda text: None, timeout=150, pause=time.sleep, wake=None):
    """Press through the screens after a race until the start screen shows with
    the cursor on Start. press(button) presses 'cross', 'circle', 'left' or
    'right'; look() returns gt7.screen.classify's name for the screen now.
    Logs each step the first time it shows. With wake=seconds, press X once
    when the screen has been unknown that long: the start screen hides its
    menu after a while without input, and X brings it back. Returns True at the
    start screen, False when it isn't reached in time."""
    deadline = time.time() + timeout
    seen = set()
    unknown_since = None
    while time.time() < deadline:
        name = look()
        if name == 'start/start':
            return True
        if name == 'unknown' and wake is not None:
            unknown_since = unknown_since or time.time()
            if time.time() - unknown_since >= wake:
                press('cross')
                wake = None
                pause(1.0)
                continue
        else:
            unknown_since = None
        step = STEPS.get(name)
        if step and step not in seen:
            seen.add(step)
            log(step)
        if name in NEXT:
            press(NEXT[name])
            pause(1.0)  # the screen changes about half a second after a press
        else:
            pause(0.5)  # a fade, the cars after the finish or something new: wait
    return False
