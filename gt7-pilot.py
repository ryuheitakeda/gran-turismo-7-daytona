#!/usr/bin/env python3

# The race loop of gt7-daytona.sh, driven with the virtual gamepad (gt7/pad.py)
# instead of keys, and reading the telemetry itself.
#
# gt7-daytona.sh runs it when PILOT=1, after reading the config, taking the lock
# and finding the Chiaki window; its settings come in as environment variables
# of the same names. It does the same steps, waits and log lines as the bash
# loop. PAD=dry logs the pad instead of making one (for tests).

import datetime
import math
import os
import signal
import subprocess
import sys
import threading
import time

from gt7 import driver, menus, pad, races, screen, telemetry

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
FINISH_WAIT = float(env('FINISH_WAIT', '8'))
RACE_PRIZE = int(env('RACE_PRIZE', '9705000'))
RACE_TIME = float(env('RACE_TIME', '800'))
START_TIMEOUT = float(env('START_TIMEOUT', '15'))
STUCK_SPEED = float(env('STUCK_SPEED', '30'))
STUCK_TIME = float(env('STUCK_TIME', '5'))
STUCK_GIVE_UP = float(env('STUCK_GIVE_UP', '60'))  # stuck this long: give up (GT7 puts a stuck car back sooner)
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
SHOTS_DIR = env('SHOTS_DIR', os.path.expanduser('~/gt7-data/shots'))  # the rewards screens (and errors)
SHOTS_KEPT = 50  # laps this much slower than after the last maintenance: say so
STEER_PROBE = env('STEER_PROBE', '') == '1'  # line: find the stick's dead zone once, on lap 3's back straight
PROBE_FROM, PROBE_TO, PROBE_MAX = 1700, 2300, 0.3  # metres along the line, and the stick it ramps up to (right)
TAPS_FILE = os.path.join(env('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'gt7-daytona.taps')  # touch it: back to taps
LOST = 8.0  # line: metres off the line at which it gives up and taps for the rest of the race


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
        if os.path.exists(TAPS_FILE):
            os.remove(TAPS_FILE)
        self.rx = telemetry.Receiver(PLAYSTATION_IP, TELEMETRY_FILE, TELEMETRY_RECORD, self.on_packet)
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

    def on_packet(self, t):
        """Every packet: each lap's time and top speed (logged when it ends), and with a
        track line, how far the car was from it and the stick it gives (used with DRIVE=line)."""
        try:
            if not t['on_track'] or t['paused'] or t['laps'] <= 0:
                return
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
        if DRIVE == 'line' and self.steering and not self.taps and self.probe(t):
            return
        if DRIVE == 'line' and self.steering and not self.taps:
            if t['packet_id'] % 30 == 0 and os.path.exists(TAPS_FILE):
                self.taps = True
                log('  Steering with taps from now on, as asked (%s)' % TAPS_FILE)
            elif abs(self.line.d) > LOST:
                self.taps = True
                log('WARNING: %.1f m off the track line; steering with taps for the rest of the race' % self.line.d)
            else:
                self.pad.stick(stick)

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

    def drive(self):
        """Steer like the key taps: the left stick fully right briefly, again and again."""
        try:
            while self.running:
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
        self.pad.press(button, DPAD_LENGTH if button in pad.DPAD else KEYPRESS_LENGTH)

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
                self.balance_after = screen.read_number(self.last_image, screen.REWARD_BALANCE)
                self.keep_shot('reward', self.last_image)

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
                # press Start only on the start screen with the cursor on it. When its menu
                # has hidden after a while without input, the X that brings it back can
                # also start the race
                refs, window = screen.references(), int(WINDOW_ID)
                reached = menus.to_start(self.menu_press, lambda: self.look(window, refs), log,
                                         30, pause=self.pause, trace=self.trace)
                if reached == 'start/start':
                    # the credits before the race, to tell the reward from the balance after it: the
                    # last rewards screen's balance (big digits) or, first, the top bar's (small, misread more)
                    self.balance_before = self.balance_after or screen.read_number(self.last_image, screen.TOP_CREDITS)
                    self.press('cross', 'start')
                elif reached == 'race':
                    log('  The race started on the X that brought back the start menu')
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
            self.taps = DRIVE != 'line' or not self.line
            self.race_laps = []
            started = time.time()
            steer_start, race_end = started + STRAIGHT_TIME, started + RACE_TIME
            slow_since, stuck, checked, result = None, False, started, ''
            while True:
                t, now = self.rx.fresh(), time.time()
                if t:
                    if t['laps'] > 0 and t['lap'] > t['laps']:
                        result = ' (P%d, best lap %s)' % (t['race_position'], lap_time(t['best']))
                        break
                    if not t['paused'] and t['speed'] < STUCK_SPEED and (t['lap'] >= 1 or now >= steer_start):
                        slow_since = slow_since or now
                        if now - slow_since >= STUCK_TIME and not stuck:
                            # keep R2 down and tap on: GT7 puts a car that's stuck back on the track
                            stuck, self.taps = True, True
                            log('  The car is stuck (lap %d, %d km/h for %ds); driving on with taps'
                                % (t['lap'], t['speed'], STUCK_TIME))
                        if now - slow_since >= STUCK_GIVE_UP:
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
                self.steering = now >= steer_start
                self.pause(0.1)
            self.steering = False
            self.pad.stick(0.0)

            log('  Race ending' + result)
            finish, seconds = t, time.time() - started
            self.snap_every(1, 'menu')  # until the next race starts
            miles += round(LAP_MILES * LAPS, 1)
            reward = None
            if result and MENUS == 'screen':
                # look at the screen before each press: skip "1st", then through the results
                self.pad.r2(0)
                self.reward_presses, self.balance_after = 0, None
                refs, window = screen.references(), int(WINDOW_ID)
                if not menus.to_start(self.menu_press, lambda: self.look(window, refs), log,
                                      pause=self.pause, trace=self.trace, after_race=True):
                    # ('race' after the screens after it: the next start finds it running)
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
