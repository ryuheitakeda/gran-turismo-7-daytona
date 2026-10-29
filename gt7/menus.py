# Go from the end of a race back to the start screen by looking at the screen
# before every press, instead of pressing on a timer (gt7/screen.py tells the
# screens apart). Works with any way of pressing: keys or the virtual pad.

import time

# what to press on each screen to get closer to the start screen
NEXT = {
    'finish': 'cross',  # "1st" after the finish line: skip it
    'start-idle': 'cross',  # the start screen's menu hid after a while: bring it back
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
# seconds a screen must stay before pressing: only the top bar also shows while the start
# screen's menu fades in or out, and an X then lands on whatever button the cursor is on
STABLE = {'start-idle': 3.0}
# an unknown screen right after these is the replay without its menu when something bright
# (a yellow line) is behind the faint GRAN TURISMO 7 in the corner: X there shows the menu
REPLAY_AFTER = ('rewards', 'replay')
REPLAY_UNKNOWN = 4.0  # seconds


def to_start(press, look, log=lambda text: None, timeout=150, pause=time.sleep, trace=None):
    """Press through the screens after a race until the start screen shows with
    the cursor on Start. press(button) presses 'cross', 'circle', 'left' or
    'right'; look() returns gt7.screen.classify's name for the screen now.
    Logs each step the first time it shows; trace(screen, button) is told of
    every press. Nothing is pressed on a screen it doesn't know, except X in
    the replay after the rewards (see REPLAY_AFTER). Returns 'start/start', or
    'race' when the race has started (an X that should only bring back the
    start screen's hidden menu can start it), or None when neither shows in time."""
    deadline = time.time() + timeout
    seen = set()
    last, since, known = None, time.time(), None
    while time.time() < deadline:
        name = look()
        if name != last:
            last, since = name, time.time()
        if name != 'unknown':
            known = name
        if name in ('start/start', 'race'):
            return name
        step = STEPS.get(name)
        if step and step not in seen:
            seen.add(step)
            log(step)
        button = None
        if name in NEXT and time.time() - since >= STABLE.get(name, 0):
            button = NEXT[name]
        elif name == 'unknown' and known in REPLAY_AFTER and time.time() - since >= REPLAY_UNKNOWN:
            button = 'cross'
        if button:
            if trace:
                trace(name, button)
            press(button)
            pause(1.0)  # the screen changes about half a second after a press
            if name == 'unknown':
                since = time.time()  # give the replay's menu time to show before another X
        else:
            pause(0.5)  # a fade, the cars after the finish or something new: wait
    return None
