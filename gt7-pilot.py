#!/usr/bin/env python3

# The race loop of gt7-daytona.sh, driven with the virtual gamepad (gt7/pad.py)
# instead of keys, and reading the telemetry itself.
#
# gt7-daytona.sh runs it when PILOT=1, after reading the config, taking the lock
# and finding the Chiaki window; its settings come in as environment variables
# of the same names. It does the same steps, waits and log lines as the bash
# loop. PAD=dry logs the pad instead of making one (for tests).

import datetime
import os
import signal
import subprocess
import sys
import threading
import time

from gt7 import menus, pad, screen, telemetry

HERE = os.path.dirname(os.path.abspath(__file__))
env = os.environ.get

PLAYSTATION_IP = env('PLAYSTATION_IP', '')
TELEMETRY_FILE = env('TELEMETRY_FILE', '')
TELEMETRY_RECORD = env('TELEMETRY_RECORD', '')
SCREEN_DIR = env('SCREEN_DIR', '')
WINDOW_ID = env('WINDOW_ID', '')
WINDOW_NAME = env('WINDOW_NAME', screen.WINDOW_NAME)
STOP_FILE = env('STOP_FILE', os.path.expanduser('~/.cache/gt7-daytona.stop-after-race'))
KEYPRESS_LENGTH = float(env('KEYPRESS_LENGTH', '0.08'))
FINISH_WAIT = float(env('FINISH_WAIT', '8'))
RACE_PRIZE = int(env('RACE_PRIZE', '9705000'))
RACE_TIME = float(env('RACE_TIME', '800'))
START_TIMEOUT = float(env('START_TIMEOUT', '15'))
STUCK_SPEED = float(env('STUCK_SPEED', '30'))
STUCK_TIME = float(env('STUCK_TIME', '5'))
STRAIGHT_TIME = float(env('STRAIGHT_TIME', '15'))
MAINTENANCE_RACES = int(env('MAINTENANCE_RACES', '20'))
LAPS = int(env('LAPS', '10'))
LAP_MILES = float(env('LAP_MILES', '2.6'))
TAP_LENGTH = float(env('TAP_LENGTH', '0.053'))  # the key taps measured on :0
TAP_INTERVAL = float(env('TAP_INTERVAL', '0.58'))
MENUS = env('MENUS', 'timer')  # screen: look at the screen before each press after the race


def log(text):
    print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + text, flush=True)


def lap_time(ms):
    return '%d:%06.3f' % (ms // 60000, ms % 60000 / 1000)


class Quit(Exception):
    """Stop racing: log the reason and leave with the exit status."""

    def __init__(self, status, reason=''):
        super().__init__(reason)
        self.status = status


class Pilot:
    def __init__(self):
        self.parent = os.getppid()
        self.running = True
        self.steering = False
        self.snaps = []
        self.snapper = None
        self.pad = pad.DryPad() if env('PAD') == 'dry' else pad.Pad()
        self.rx = telemetry.Receiver(PLAYSTATION_IP, TELEMETRY_FILE, TELEMETRY_RECORD)
        threading.Thread(target=self.rx.run, args=(lambda: self.running,), daemon=True).start()
        threading.Thread(target=self.drive, daemon=True).start()

    def close(self):
        self.running = self.steering = False
        self.pad.close()
        for p in self.snaps + [self.snapper]:
            if p and p.poll() is None:
                p.terminate()
        if TELEMETRY_FILE:
            try:
                os.remove(TELEMETRY_FILE)
            except OSError:
                pass

    def pause(self, seconds):
        """Sleep, but quit when gt7-daytona.sh is gone."""
        end = time.time() + seconds
        while True:
            if os.getppid() != self.parent:
                raise Quit(1)
            left = end - time.time()
            if left <= 0:
                return
            time.sleep(min(left, 0.1))

    def drive(self):
        """Steer like the key taps: the left stick fully right briefly, again and again."""
        try:
            while self.running:
                if self.steering:
                    self.pad.stick(1.0)
                    time.sleep(TAP_LENGTH)
                    self.pad.stick(0.0)
                    time.sleep(max(0.0, TAP_INTERVAL - TAP_LENGTH))
                else:
                    time.sleep(0.02)
        except (OSError, TypeError):
            pass  # the pad was closed on the way out

    def check_window(self):
        for _ in range(5):
            try:
                screen.find_window(WINDOW_NAME)
                return
            except RuntimeError:
                time.sleep(0.2)
        raise Quit(1, 'ERROR: the Chiaki stream window is gone (stream disconnected?)')

    def snap(self, label):
        if not SCREEN_DIR:
            return
        self.snaps = [p for p in self.snaps if p.poll() is None]
        name = '%s-race%d-%s.png' % (datetime.datetime.now().strftime('%H%M%S.%f')[:8], self.count, label)
        self.snaps.append(subprocess.Popen(
            [os.path.join(HERE, 'gt7-screen.py'), 'snap', '--id', WINDOW_ID, os.path.join(SCREEN_DIR, name)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def snap_every(self, seconds, label):
        if not SCREEN_DIR:
            return
        if self.snapper and self.snapper.poll() is None:
            self.snapper.terminate()
            self.snapper.wait()
        self.snapper = subprocess.Popen(
            [os.path.join(HERE, 'gt7-screen.py'), 'record', '--id', WINDOW_ID, '--every', str(seconds),
             SCREEN_DIR, 'race%d-%s' % (self.count, label)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def press(self, button, label=None):
        if label:
            self.snap(label)
        self.check_window()
        self.pad.press(button, KEYPRESS_LENGTH)
        self.pause(0.1)  # like the time xdotool takes, so two presses stay apart

    def start(self):
        if isinstance(self.pad, pad.Pad):
            device, deadline = self.pad.device(), time.time() + 5
            while not pad.opened_by(device):
                if time.time() > deadline:
                    raise Quit(1, 'ERROR: Chiaki did not open the virtual pad %s (is 70-gt7-pad.rules '
                                  'installed?)' % device)
                self.pause(0.1)
        for _ in range(10):
            self.pause(1)
            if self.rx.fresh():
                break
        if self.rx.fresh():
            log('Telemetry from %s' % PLAYSTATION_IP)
        else:
            log('WARNING: no telemetry from %s (is UDP port 33740 open?); timing the race with RACE_TIME'
                % PLAYSTATION_IP)

    def timed_menus(self, result, money, miles):
        """The presses after the race on a timer, for when the screens aren't learned."""
        if result:
            # telemetry saw the car cross the line, so no buffer for a late finish is needed
            self.pad.r2(0)
            self.pause(FINISH_WAIT)
            log('Standings')
        else:
            self.pause(30)
            self.pad.r2(0)
            log('Standings')
            self.pause(20)  # extra wait here to buffer for slow finishes
        self.press('cross', 'standings')

        log('Rewards')
        self.press('cross', 'rewards')
        self.pause(3)

        log('  Credits: {:,}'.format(money))
        self.press('cross', 'credits')
        self.pause(2)

        log('  Miles: %.1f' % miles)
        self.press('cross', 'miles')
        self.pause(4)

        log('Replay')
        self.press('cross', 'replay1')  # the replay's menu, with the cursor on Exit
        self.pause(4)
        self.press('cross', 'replay2')  # Exit: the race result with Replay, Retry and Exit
        self.pause(4)

        log('Retry')
        self.press('right', 'retry-right')  # from Replay to Retry
        self.pause(1)
        self.press('cross', 'retry-x')
        self.pause(4)

    def race(self):
        self.count = 0
        money, miles = 0, 0.0
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
        while True:
            if os.path.exists(STOP_FILE):
                os.remove(STOP_FILE)
                log('Stopped after the race as requested; the game is at the start screen')
                return
            self.count += 1
            log('Race %d' % self.count)
            if MENUS == 'screen':
                # press Start only on the start screen with the cursor on it (X brings back
                # its menu when it has hidden after a while without input)
                refs, window = screen.references(), int(WINDOW_ID)
                if not menus.to_start(lambda button: self.pad.press(button, KEYPRESS_LENGTH),
                                      lambda: screen.classify(screen.capture(window), refs)[0], log,
                                      30, pause=self.pause):
                    raise Quit(1, 'ERROR: not on the start screen')
            elif self.count == 1:
                # the start screen hides its menu after a while without input, and the
                # first X only brings it back; if the menu was showing, this X starts the
                # race and the next one lands on the loading screen
                self.press('cross', 'start-wake')
                self.pause(2)
            self.press('cross', 'start')
            self.pause(2)
            self.pad.r2(1)  # hold only during the race, never in the menus
            self.pause(6)

            deadline = time.time() + START_TIMEOUT - 8
            while True:
                t = self.rx.fresh()
                if not t or t['on_track']:
                    break
                if time.time() >= deadline:
                    raise Quit(1, 'ERROR: the race did not start (telemetry: the car is not on track)')
                self.pause(0.5)

            if self.rx.fresh():
                log('  Race start (telemetry: Race ending at the finish line)')
            else:
                log('  Race start (Race ending at %s)'
                    % (datetime.datetime.now() + datetime.timedelta(seconds=RACE_TIME)).strftime('%H:%M:%S'))
            self.snap_every(30, 'race')
            started = time.time()
            steer_start, race_end = started + STRAIGHT_TIME, started + RACE_TIME
            slow_since, checked, result = None, started, ''
            while True:
                t, now = self.rx.fresh(), time.time()
                if t:
                    if t['laps'] > 0 and t['lap'] > t['laps']:
                        result = ' (P%d, best lap %s)' % (t['race_position'], lap_time(t['best']))
                        break
                    if not t['paused'] and t['speed'] < STUCK_SPEED and (t['lap'] >= 1 or now >= steer_start):
                        slow_since = slow_since or now
                        if now - slow_since >= STUCK_TIME:
                            raise Quit(1, 'ERROR: the car is stuck (lap %d, %d km/h for %ds)'
                                       % (t['lap'], t['speed'], STUCK_TIME))
                    else:
                        slow_since = None
                    if now >= race_end + 120:
                        raise Quit(1, 'ERROR: no finish after %ds (lap %d of %d)'
                                   % (RACE_TIME + 120, t['lap'], t['laps']))
                elif now >= race_end:
                    break
                if now - checked >= 5:
                    self.check_window()
                    checked = now
                self.steering = now >= steer_start
                self.pause(0.1)
            self.steering = False
            self.pad.stick(0.0)

            log('  Race ending' + result)
            self.snap_every(1, 'menu')  # until the next race starts
            miles += round(LAP_MILES * LAPS, 1)
            money += RACE_PRIZE
            if result and MENUS == 'screen':
                # look at the screen before each press: skip "1st", then through the results
                self.pad.r2(0)
                refs, window = screen.references(), int(WINDOW_ID)
                if not menus.to_start(lambda button: self.pad.press(button, KEYPRESS_LENGTH),
                                      lambda: screen.classify(screen.capture(window), refs)[0], log,
                                      pause=self.pause):
                    raise Quit(1, 'ERROR: the screens after the race did not lead back to the start screen')
                log('  Credits: {:,}'.format(money))
                log('  Miles: %.1f' % miles)
            else:
                self.timed_menus(result, money, miles)

            if MAINTENANCE_RACES > 0 and self.count % MAINTENANCE_RACES == 0:
                log('  %d races done: check the oil and engine condition' % self.count)


def main():
    if not PLAYSTATION_IP:
        sys.exit('PILOT=1 needs PLAYSTATION_IP: it reads the telemetry itself')
    statuses = {signal.SIGHUP: 129, signal.SIGINT: 130, signal.SIGTERM: 143}

    def on_signal(signum, frame):
        raise Quit(statuses[signum])
    for sig in statuses:
        signal.signal(sig, on_signal)
    status = 0
    try:
        pilot = Pilot()
    except OSError as e:
        log('ERROR: cannot make the virtual pad: %s (is /dev/uinput writable?)' % e)
        sys.exit(1)
    pilot.count = 0
    try:
        pilot.start()
        pilot.race()
    except Quit as e:
        if str(e):
            log(str(e))
        status = e.status
    finally:
        pilot.close()
    sys.exit(status)


main()
