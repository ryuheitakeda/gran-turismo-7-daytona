#!/usr/bin/env python3

# The race loop of gt7-daytona.sh, driven with the virtual gamepad (gt7/pad.py)
# instead of keys, and reading the telemetry itself.
#
# gt7-daytona.sh runs it when PILOT=1, after reading the config, taking the lock
# and finding the Chiaki window; its settings come in as environment variables
# of the same names. It does the same steps, waits and log lines as the bash
# loop. PAD=dry logs the pad instead of making one (for tests).

import datetime
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time

from gt7 import driver, menus, minimap, pad, races, screen, telemetry

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
DPAD_LENGTH = float(env('DPAD_LENGTH', '0.08'))  # held longer, GT7 moves the cursor twice
MENU_KEYS = env('MENU_KEYS', '1') == '1'  # press the menus with the keys (xdotool): the pad's presses get lost there
KEYS = {'cross': env('KEY_X', 'Return'), 'circle': env('KEY_O', 'BackSpace'),
        'left': env('DPAD_L', 'Left'), 'right': env('DPAD_R', 'Right')}
FINISH_WAIT = float(env('FINISH_WAIT', '8'))
RACE_PRIZE = int(env('RACE_PRIZE', '9705000'))
RACE_TIME = float(env('RACE_TIME', '800'))
START_TIMEOUT = float(env('START_TIMEOUT', '15'))
STUCK_SPEED = float(env('STUCK_SPEED', '30'))
STUCK_TIME = float(env('STUCK_TIME', '5'))
STUCK_GIVE_UP = float(env('STUCK_GIVE_UP', '60'))  # stuck this long: give up (GT7 puts a stuck car back sooner)
STUCK_RETRY = float(env('STUCK_RETRY', '20'))  # stuck this long: pause and retry the race (0: never)
# the launch: full R2 and no steering is right with traction control 5; with 3, full R2 spun the
# rear out and the car turned right into the wall (4 of 9 starts, 2026-10-30), and 0.5 here
# with LAUNCH_KPSI 2 is the untried fix for that
LAUNCH_THROTTLE = float(env('LAUNCH_THROTTLE', '1'))  # R2 from standstill
LAUNCH_TIME = float(env('LAUNCH_TIME', '3'))  # seconds from moving off to full R2 (LAUNCH_THROTTLE for the first third)
LAUNCH_KPSI = float(env('LAUNCH_KPSI', '0'))  # line, until STRAIGHT_TIME: stick per radian of heading towards the wall
LAUNCH_MAX = float(env('LAUNCH_MAX', '0.5'))  # the most stick then
RETRY_FILE = os.path.join(env('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'gt7-daytona.retry')  # touch it: retry the race now
STRAIGHT_TIME = float(env('STRAIGHT_TIME', '15'))
MAINTENANCE_RACES = int(env('MAINTENANCE_RACES', '20'))
LAPS = int(env('LAPS', '10'))
LAP_MILES = float(env('LAP_MILES', '2.6'))
TAP_LENGTH = float(env('TAP_LENGTH', '0.053'))  # the key taps measured on :0
TAP_INTERVAL = float(env('TAP_INTERVAL', '0.58'))
MENUS = env('MENUS', 'timer')  # screen: look at the screen before each press after the race
DRIVE = env('DRIVE', 'pwm')  # pwm: key-like taps; shadow: taps, and log what line would do; line: steer by the line
WALL_GAP = float(env('WALL_GAP', '0.3'))  # line: metres inside the wall line to aim for
STEER_KD = float(env('STEER_KD', '0.1'))  # line: stick per metre off the aim
STEER_KPSI = float(env('STEER_KPSI', '1.0'))  # line: stick per radian of heading towards the wall
STEER_MAX = float(env('STEER_MAX', '0.3'))  # line: the most stick either way
CURVE_STICK = float(env('CURVE_STICK', '0'))  # line: left stick added in the sharpest bend (less elsewhere)
MENU_TRACE = env('MENU_TRACE', '') == '1'  # log every press on the screens after the race
MAINT_LAP_PCT = float(env('MAINT_LAP_PCT', '1.5'))
TRAFFIC = env('TRAFFIC', 'log')  # read the course map once a second in the race: off, log (cars close ahead)
TRAFFIC_WITHIN = float(env('TRAFFIC_WITHIN', '200'))  # metres ahead that count as close
TRAFFIC_FILE = env('TRAFFIC_FILE', os.path.expanduser('~/gt7-data/traffic.jsonl'))
TRAFFIC_ACTION = env('TRAFFIC_ACTION', 'none')  # none, or inside: on a straight, hold the stick left while a car is close ahead
TRAFFIC_STICK = float(env('TRAFFIC_STICK', '-0.25'))
NITRO = env('NITRO', 'off')  # straights: hold NITRO_BUTTON in NITRO_ZONES, metres along the track line
NITRO_BUTTON = env('NITRO_BUTTON', 'l3')  # GT7's nitrous button (R3 did nothing, 2026-10-30)
# where the car speeds up and traction control 5 doesn't cut the power: it does almost all the
# time in the bankings and the tri-oval, and nitrous there would be wasted
NITRO_ZONES = [tuple(float(v) for v in z.split('-')) for z in env('NITRO_ZONES', '1600-2300,300-550,3450-3650').split(',')]
STRAIGHTS = [(1700, 2400), (3700, 4100), (0, 500)]  # where TRAFFIC_ACTION=inside may move the car
SHOTS_DIR = env('SHOTS_DIR', os.path.expanduser('~/gt7-data/shots'))  # the rewards screens (and errors)
SHOTS_KEPT = 50  # laps this much slower than after the last maintenance: say so
STEER_PROBE = env('STEER_PROBE', '') == '1'  # line: find the stick's dead zone once, on lap 3's back straight
PROBE_FROM, PROBE_TO, PROBE_MAX = 1700, 2300, 0.3  # metres along the line, and the stick it ramps up to (right)
TAPS_FILE = os.path.join(env('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'gt7-daytona.taps')  # touch it: back to taps
LOST = 8.0  # line: metres off the line at which it stops steering and drives straight until back within half of it


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
        self.line, self.taps, self.lap_log, self.race_laps = None, DRIVE != 'line', {}, []
        self.last_image, self.reward_presses, self.balance_before, self.balance_after = None, 0, None, None
        if DRIVE in ('shadow', 'line'):
            try:
                self.line = driver.LineDriver(driver.Track.load(), WALL_GAP, STEER_KD, STEER_KPSI, STEER_MAX,
                                              CURVE_STICK)
            except (OSError, ValueError, KeyError) as e:
                log('WARNING: no track line (%s); steering with taps' % e)
                self.taps = True
        for stale in (TAPS_FILE, RETRY_FILE):
            if os.path.exists(stale):
                os.remove(stale)
        # (before the telemetry thread, whose on_packet reads them)
        self.override_until, self.nitro_on, self.r2_on, self.off_line = 0.0, False, False, False
        self.r2_level, self.moving_since, self.launching = 0.0, None, False
        self.rx = telemetry.Receiver(PLAYSTATION_IP, TELEMETRY_FILE, TELEMETRY_RECORD, self.on_packet)
        threading.Thread(target=self.rx.run, args=(lambda: self.running,), daemon=True).start()
        threading.Thread(target=self.drive, daemon=True).start()
        if TRAFFIC != 'off' and WINDOW_ID:
            threading.Thread(target=self.watch_traffic, daemon=True).start()

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

    def on_packet(self, t):
        """Every packet: each lap's time and top speed (logged when it ends), and with a
        track line, how far the car was from it and the stick it gives (used with DRIVE=line)."""
        try:
            if not t['on_track'] or t['paused'] or t['laps'] <= 0:
                return
            if self.r2_on:
                now = time.time()
                if t['speed'] < 5:
                    self.moving_since, level = None, LAUNCH_THROTTLE  # standing: launch again
                else:
                    self.moving_since = self.moving_since or now
                    ramp = min(1.0, max(0.0, (now - self.moving_since) / LAUNCH_TIME * 1.5 - 0.5))
                    level = round(LAUNCH_THROTTLE + (1.0 - LAUNCH_THROTTLE) * ramp, 2)
                if level != self.r2_level:
                    self.r2_level = level
                    self.pad.r2(level)
            stick = self.line.update(t) if self.line else None
            self.count_lap(t, stick)
            if stick is not None:
                self.steer_by_line(t, stick)
        except Exception as e:  # never let it stop the telemetry
            if not self.taps:
                self.taps = True
                log('WARNING: steering by the line failed (%r); steering with taps' % e)

    def count_lap(self, t, stick):
        lap = self.lap_log
        if t['lap'] != lap.get('lap'):
            if lap.get('n', 0) >= 600 and 1 <= lap['lap'] <= t['laps']:  # a whole lap, not the start
                seconds = t['time'] - lap['start']
                self.race_laps.append((lap['lap'], seconds, lap['vmax']))
                text = '  Lap %d %s max %d km/h' % (lap['lap'], lap_time(round(1000 * seconds)), lap['vmax'])
                if lap['line']:
                    text += ', d %.2f m (%.2f..%.2f), heading %.1f deg, stick %.3f (%s)' % (
                        lap['d'] / lap['line'], lap['dmin'], lap['dmax'],
                        math.degrees(lap['psi'] / lap['line']), lap['stick'] / lap['line'],
                        'taps' if self.taps else DRIVE)
                log(text)
            lap.clear()
            lap.update(lap=t['lap'], n=0, start=t['time'], vmax=0.0,
                       line=0, d=0.0, psi=0.0, stick=0.0, dmin=99.0, dmax=-99.0)
        lap['n'] += 1
        lap['vmax'] = max(lap['vmax'], t['speed'])
        if stick is not None:
            lap['line'] += 1
            lap['d'] += self.line.d
            lap['psi'] += self.line.psi
            lap['stick'] += stick
            lap['dmin'], lap['dmax'] = min(lap['dmin'], self.line.d), max(lap['dmax'], self.line.d)

    def steer_by_line(self, t, stick):
        if DRIVE == 'line' and LAUNCH_KPSI and self.launching and not self.taps and t['speed'] > 15:  # (psi is fresh above 11)
            # from the grid until STRAIGHT_TIME: keep the heading along the line (steer left as
            # soon as it turns towards the wall), without the pull to the wall. Straight on, the
            # rear stepped out and the car met the wall nose-first at 50 km/h, again and again
            # with traction control 3 (2026-10-30 02:12-02:53)
            self.pad.stick(max(-LAUNCH_MAX, min(LAUNCH_MAX, -LAUNCH_KPSI * self.line.psi)))
            return
        if DRIVE == 'line' and self.steering and not self.taps and self.probe(t):
            return
        if DRIVE == 'line' and self.steering and not self.taps:
            if t['packet_id'] % 30 == 0 and os.path.exists(TAPS_FILE):
                self.taps = True
                log('  Steering with taps from now on, as asked (%s)' % TAPS_FILE)
            elif abs(self.line.d) > (LOST / 2 if self.off_line else LOST):
                # thrown off the line (hit by a car, spun): drive straight, without steering, until
                # the banking takes the car back out to the wall. Taps there pushed the slow car
                # into the wall again and again until the race had to be retried (2026-10-30 01:57)
                if not self.off_line:
                    self.off_line = True
                    log('WARNING: %.1f m off the track line; driving straight until back on it' % self.line.d)
                self.pad.stick(0.0)
            else:
                if self.off_line:
                    self.off_line = False
                    log('  Back on the track line (%.1f m off it)' % self.line.d)
                if time.time() < self.override_until:
                    self.pad.stick(TRAFFIC_STICK)  # moving inside past a car ahead
                else:
                    self.pad.stick(stick)
        if NITRO == 'straights' and self.line:
            station = self.line.hint * driver.SPACING
            want = self.steering and any(a <= station <= b for a, b in NITRO_ZONES)
            if want != self.nitro_on:
                self.nitro_on = want
                self.pad.button(NITRO_BUTTON, want)

    def watch_traffic(self):
        """Once a second in the race: read the course map and log a car close ahead; with
        TRAFFIC_ACTION=inside, hold the stick left for a moment on a straight."""
        traffic, window, last_log = minimap.Traffic(TRAFFIC_WITHIN), int(WINDOW_ID), 0.0
        while self.running:
            started = time.time()
            if self.steering:
                try:
                    metres, cars = traffic.update(screen.capture(window))
                    if metres is not None:
                        station = self.line.hint * driver.SPACING if self.line else None
                        t = self.rx.fresh()
                        if started - last_log >= 5:
                            last_log = started
                            log('  Traffic: a car %d m ahead%s, %d on the map' % (
                                metres, ' at %d m' % station if station is not None else '', cars))
                        with open(TRAFFIC_FILE, 'a') as f:
                            f.write(json.dumps({'time': datetime.datetime.now().isoformat(timespec='seconds'),
                                                'metres': round(metres), 'station': station and round(station),
                                                'speed': t and round(t['speed']), 'lap': t and t['lap'],
                                                'cars': cars}) + '\n')
                        if TRAFFIC_ACTION == 'inside' and station is not None and \
                                any(a <= station <= b for a, b in STRAIGHTS):
                            self.override_until = time.time() + 1.5
                except Exception as e:
                    log('WARNING: the course map could not be read (%s)' % e)
                    time.sleep(5)
            time.sleep(max(0.0, 1.0 - (time.time() - started)))

    def probe(self, t):
        """With STEER_PROBE, on lap 3's back straight ramp the stick from 0 to PROBE_MAX to
        the right (into the wall the car rides, away from the cars inside) and log at what
        stick the steering starts to turn. True while it holds the stick."""
        if not STEER_PROBE or t['lap'] != 3 or t['steer'] is None or getattr(self, 'probed', False):
            return False
        s = self.line.hint * driver.SPACING
        if not PROBE_FROM <= s <= PROBE_TO:
            if getattr(self, 'probe_seen', None):
                self.probed = True
                seen = self.probe_seen
                start = next((k for k, a in seen if abs(a) > 0.5), None)
                log('  Probe: the steering starts to turn at stick %s; %s' % (
                    '%.3f' % start if start is not None else 'over %.2f' % PROBE_MAX,
                    ', '.join('%.2f: %.1f deg' % (k, a) for k, a in seen[::max(1, len(seen) // 6)])))
                self.pad.stick(0.0)
            return False
        stick = PROBE_MAX * (s - PROBE_FROM) / (PROBE_TO - PROBE_FROM)
        self.pad.stick(stick)
        self.probe_seen = getattr(self, 'probe_seen', None) or []
        self.probe_seen.append((stick, -math.degrees(t['steer'])))  # the recordings show right as negative
        return True

    def throttle(self, on):
        """Hold R2 down, or let it go. The pad only sends changes, and GT7 drops the one
        sent while a race loads, so drive() keeps nudging it while it is down. From
        standstill it starts at LAUNCH_THROTTLE and on_packet takes it to full over
        LAUNCH_TIME: with traction control 3, full R2 from the grid spun the rear wheels,
        the car turned right on the banking and stuck nose-first in the wall, three starts
        in a row (2026-10-30 02:12). (Held at half until 120 km/h, the gearbox stayed in
        first and the car crawled at 60 km/h, 02:28.)"""
        self.r2_on = on
        self.r2_level = LAUNCH_THROTTLE if on else 0.0
        self.moving_since = None
        self.pad.r2(self.r2_level)

    def drive(self):
        """Steer like the key taps: the left stick fully right briefly, again and again,
        and nudge R2 once a second while it is held (98%, then 100% again)."""
        nudged = 0.0
        try:
            while self.running:
                if self.r2_on and time.time() - nudged >= 1.0:
                    nudged = time.time()
                    level = self.r2_level
                    self.pad.r2(level - 0.02)
                    self.pad.r2(level)
                if self.steering and self.taps:
                    self.pad.stick(1.0)
                    time.sleep(TAP_LENGTH)
                    self.pad.stick(0.0)
                    time.sleep(max(0.0, TAP_INTERVAL - TAP_LENGTH))
                else:
                    time.sleep(0.02)
        except (OSError, TypeError):
            pass  # the pad was closed on the way out

    def keep_race(self, t, seconds, reward=None, balance=None):
        """A line in RACES_FILE for the race just finished, and a word when the laps have
        got slower than after the last maintenance (#22)."""
        laps = sorted(self.race_laps)
        later = sorted(s for n, s, v in laps if n >= 2)
        record = {
            'time': datetime.datetime.now().isoformat(timespec='seconds'),
            'position': t['race_position'], 'seconds': round(seconds, 1),
            'laps': [round(s, 3) for n, s, v in laps],
            'median': round(later[len(later) // 2], 3) if later else None,
            'best': t['best'] / 1000 if t['best'] > 0 else None,
            'max_speed': round(max((v for n, s, v in laps), default=0)),
            'drive': 'taps' if self.taps else DRIVE, 'prize': RACE_PRIZE,
            'reward': reward, 'balance': balance,
        }
        try:
            races.append(record)
            state = races.wear(races.load(), record['drive'])
        except OSError as e:
            log('WARNING: cannot keep the race in %s (%s)' % (races.RACES_FILE, e))
            return
        if state and state['percent'] >= MAINT_LAP_PCT:
            log('  Maintenance: the laps are %.1f%% slower than after the last one (%s against %s); '
                'time for an oil change or an engine overhaul?' % (
                    state['percent'], lap_time(round(1000 * state['now'])), lap_time(round(1000 * state['base']))))

    def menu_press(self, button):
        if button == 'options':  # only the pad has it (the key is not known)
            self.pad.press('options', KEYPRESS_LENGTH)
        elif MENU_KEYS and WINDOW_ID and button in KEYS and not isinstance(self.pad, pad.DryPad):
            # one xdotool, so the key is held exactly 0.08 s (longer, GT7 moves the cursor twice)
            subprocess.run(['xdotool', 'keydown', '--window', WINDOW_ID, KEYS[button], 'sleep', '0.08',
                            'keyup', '--window', WINDOW_ID, KEYS[button]], check=False)
        else:
            self.pad.press(button, DPAD_LENGTH if button in pad.DPAD else KEYPRESS_LENGTH)

    def top_credits(self, window):
        """The credits in the start screen's top bar, when two reads a second apart agree."""
        values = []
        for _ in range(3):
            self.pause(1.0)
            values.append(screen.read_number(screen.capture(window), screen.TOP_CREDITS))
            if len(values) >= 2 and values[-1] is not None and values[-1] == values[-2]:
                return values[-1]
        log('  WARNING: the credits in the top bar read %s; no reward for this race' % values)
        return None

    def look(self, window, refs):
        self.last_image = screen.capture(window)
        return screen.classify(self.last_image, refs)[0]

    def trace(self, name, button):
        if MENU_TRACE:
            log('    (%s on %s)' % (button, name))
        if name == 'rewards':
            # the first X fills in the credits: before the next one the balance is final
            self.reward_presses += 1
            if self.reward_presses == 2 and self.last_image:
                self.balance_after = self.read_balance(self.last_image)
                self.keep_shot('reward', self.last_image)

    def read_balance(self, image):
        """The balance on the rewards screen, or None. Its digits are white, or pink or red
        for a moment after they change, and the usual reading loses pink and red strokes
        ('8' for 807,283,200, nothing for 828,583,200 on 2026-10-30). Reading by the red
        channel gets those but now and then merges white digits (5 as 9), so it is tried
        only when the usual reading comes out cut short, and kept only when it fits the
        balance before the race (when that is known)."""
        before = self.balance_before
        value = screen.read_number(image, screen.REWARD_BALANCE, bright=150)
        if value is not None and value >= 1000000 and (not before or len(str(value)) >= len(str(before))):
            return value
        value = screen.read_number(image, screen.REWARD_BALANCE, colour=True)
        if value is not None and value >= 1000000 and (
                not before or 0 < value - before <= 1.2 * RACE_PRIZE):
            return value
        return None

    def retry_race(self):
        """Pause the race and pick Retry; it restarts at the grid. True when the race shows again."""
        self.steering = False
        self.throttle(False)
        self.pad.stick(0.0)
        log('  Retrying the race from the pause menu')
        refs, window = screen.references(), int(WINDOW_ID)
        return menus.retry_race(self.menu_press, lambda: self.look(window, refs), log,
                                pause=self.pause, trace=self.trace, racing=self.racing)

    def racing(self):
        """The telemetry says the race runs and isn't paused."""
        t = self.rx.fresh()
        return bool(t and t['on_track'] and not t['paused'] and not t['loading'])

    def error_shot(self):
        """Keep a screenshot of the window for the web page before quitting on an error."""
        try:
            self.keep_shot('error', screen.capture(int(WINDOW_ID)))
        except Exception as e:
            log('WARNING: no error screenshot (%s)' % e)

    def keep_shot(self, kind, image):
        """Save SHOTS_DIR/<kind>-<time>.png, keeping the newest SHOTS_KEPT of the kind."""
        try:
            os.makedirs(SHOTS_DIR, exist_ok=True)
            screen.save_png(os.path.join(SHOTS_DIR, '%s-%s.png' % (kind, time.strftime('%Y%m%d-%H%M%S'))), *image)
            old = sorted(f for f in os.listdir(SHOTS_DIR) if f.startswith(kind + '-') and f.endswith('.png'))
            for f in old[:-SHOTS_KEPT]:
                os.remove(os.path.join(SHOTS_DIR, f))
        except OSError as e:
            log('WARNING: cannot keep the screenshot (%s)' % e)

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
        self.menu_press(button)
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
            self.throttle(False)
            self.pause(FINISH_WAIT)
            log('Standings')
        else:
            self.pause(30)
            self.throttle(False)
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
        restarted = False
        while True:
            # (not right after a retry: the race runs again from the grid, and a new script
            # taking it over late left the car on the wall at the start, 2026-10-30 01:58)
            if os.path.exists(STOP_FILE) and not restarted:
                os.remove(STOP_FILE)
                log('Stopped after the race as requested; the game is at the start screen')
                return
            self.count += 1
            log('Race %d' % self.count)
            if MENUS == 'screen':
                # press Start only on the start screen with the cursor on it. When its menu
                # has hidden after a while without input, the X that brings it back can
                # also start the race
                refs, window = screen.references(), int(WINDOW_ID)
                reached = menus.to_start(self.menu_press, lambda: self.look(window, refs), log,
                                         30, pause=self.pause, trace=self.trace)
                if reached is None:
                    self.error_shot()
                if reached == 'start/start':
                    # the credits before the race, to tell the reward from the balance after it: the
                    # last rewards screen's balance (big digits) or, first, the top bar's (small; read
                    # twice a second apart, since its digits roll for a moment after a race)
                    self.balance_before = self.balance_after or self.top_credits(window)
                    self.press('cross', 'start')
                elif reached == 'race':
                    log('  The race is already running (restarted, or started by the X that woke the menu)')
                else:
                    raise Quit(1, 'ERROR: not on the start screen')
            else:
                if self.count == 1:
                    # the start screen hides its menu after a while without input, and the
                    # first X only brings it back; if the menu was showing, this X starts the
                    # race and the next one lands on the loading screen
                    self.press('cross', 'start-wake')
                    self.pause(2)
                self.press('cross', 'start')
            self.pause(2)
            self.throttle(True)  # hold only during the race, never in the menus
            self.pause(6)

            deadline = time.time() + START_TIMEOUT - 8
            while True:
                t = self.rx.fresh()
                if not t or t['on_track']:
                    break
                if time.time() >= deadline:
                    self.error_shot()
                    raise Quit(1, 'ERROR: the race did not start (telemetry: the car is not on track)')
                self.pause(0.5)

            if self.rx.fresh():
                log('  Race start (telemetry: Race ending at the finish line)')
            else:
                log('  Race start (Race ending at %s)'
                    % (datetime.datetime.now() + datetime.timedelta(seconds=RACE_TIME)).strftime('%H:%M:%S'))
            self.snap_every(30, 'race')
            self.taps = DRIVE != 'line' or not self.line
            self.off_line = False
            self.race_laps = []
            started = time.time()
            steer_start, race_end = started + STRAIGHT_TIME, started + RACE_TIME
            slow_since, stuck, checked, result = None, False, started, ''
            retried = restarted = False
            while True:
                t, now = self.rx.fresh(), time.time()
                if t:
                    if t['laps'] > 0 and t['lap'] > t['laps']:
                        result = ' (P%d, best lap %s)' % (t['race_position'], lap_time(t['best']))
                        break
                    if not t['paused'] and t['speed'] < STUCK_SPEED and (t['lap'] >= 1 or now >= steer_start):
                        slow_since = slow_since or now
                        if now - slow_since >= STUCK_TIME and not stuck:
                            # keep R2 down and drive on as before: GT7 puts a car that's stuck back on
                            # the track (taps, which the line used to switch to here, only pushed a
                            # slow car into the wall again)
                            stuck = True
                            log('  The car is stuck (lap %d, %d km/h for %ds); driving on'
                                % (t['lap'], t['speed'], STUCK_TIME))
                            if t['lap'] == 0:
                                # still on the grid: twice R2 pressed after the race had shown went
                                # unseen (2026-10-29 23:06, 2026-10-30 01:06); let go and press again
                                self.throttle(False)
                                self.pause(0.5)
                                self.throttle(True)
                                log('  Still on the grid: R2 let go and pressed again')
                        if STUCK_RETRY > 0 and now - slow_since >= STUCK_RETRY and not retried \
                                and screen.references():  # the pause menu is told by the screen
                            retried = True
                            if self.retry_race():
                                restarted = True
                                break
                            log('WARNING: could not retry the race from the pause menu')
                        if now - slow_since >= STUCK_GIVE_UP:
                            self.error_shot()
                            raise Quit(1, 'ERROR: the car is stuck (lap %d, %d km/h for %ds)'
                                       % (t['lap'], t['speed'], STUCK_GIVE_UP))
                    else:
                        if stuck:
                            stuck = False
                            log('  Moving again (lap %d, %d km/h)' % (t['lap'], t['speed']))
                        slow_since = None
                    if now >= race_end + 120:
                        raise Quit(1, 'ERROR: no finish after %ds (lap %d of %d)'
                                   % (RACE_TIME + 120, t['lap'], t['laps']))
                elif now >= race_end:
                    break
                if now - checked >= 5:
                    self.check_window()
                    checked = now
                    if os.path.exists(RETRY_FILE) and screen.references():
                        os.remove(RETRY_FILE)
                        log('  Retrying the race as asked (%s)' % RETRY_FILE)
                        if self.retry_race():
                            restarted = True
                            break
                        log('WARNING: could not retry the race from the pause menu')
                self.steering = now >= steer_start
                self.launching = not self.steering
                self.pause(0.1)
            self.steering = self.launching = False
            self.pad.stick(0.0)
            if self.nitro_on:
                self.nitro_on = False
                self.pad.button(NITRO_BUTTON, False)
            if restarted:
                log('  The race starts again from the grid')
                self.count -= 1  # the same race again
                continue

            log('  Race ending' + result)
            finish, seconds = t, time.time() - started
            self.snap_every(1, 'menu')  # until the next race starts
            miles += round(LAP_MILES * LAPS, 1)
            reward = None
            if result and MENUS == 'screen':
                # look at the screen before each press: skip "1st", then through the results
                self.throttle(False)
                self.reward_presses, self.balance_after = 0, None
                refs, window = screen.references(), int(WINDOW_ID)
                if not menus.to_start(self.menu_press, lambda: self.look(window, refs), log,
                                      pause=self.pause, trace=self.trace, after_race=True):
                    # ('race' after the screens after it: the next start finds it running)
                    self.error_shot()
                    raise Quit(1, 'ERROR: the screens after the race did not lead back to the start screen')
                if self.balance_before and self.balance_after and \
                        0 < self.balance_after - self.balance_before <= 1.2 * RACE_PRIZE:
                    reward = self.balance_after - self.balance_before
                    log('  Reward: {:,} Cr (balance {:,})'.format(reward, self.balance_after))
                    if reward < 0.9 * RACE_PRIZE:
                        log('  WARNING: the reward was {:,} Cr, less than RACE_PRIZE ({:,}): '
                            'no clean race bonus?'.format(reward, RACE_PRIZE))
                money += reward or RACE_PRIZE
                log('  Credits: {:,}'.format(money))
                log('  Miles: %.1f' % miles)
            else:
                money += RACE_PRIZE
                self.timed_menus(result, money, miles)
            if result:
                self.keep_race(finish, seconds, reward, self.balance_after)

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
