#!/usr/bin/env python3

# Gran Turismo 7 Daytona Autopilot Script
#
# This work © 2025 by Jason Lonsberry is licensed under CC BY-NC-SA 4.0.
# To view a copy of this license, visit https://creativecommons.org/licenses/by-nc-sa/4.0/
#
# Usage: gt7_daytona.py [run|start|stop|status|log [lines]|check] [--yes] [--ip IP]
#   run (default)  run in the foreground, quit with CTRL+C
#   start          run in the background, writing to LOG_FILE
#   stop / status / log
#   check          test the setup (window, keys, telemetry, firewall) without racing
#
# Windows: sends keys with SendInput to the Chiaki window (brought to the front).
# Linux:   sends keys with xdotool (X11).

import argparse
import collections
import ctypes
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

WINDOWS = os.name == 'nt'
if WINDOWS:
    import msvcrt
else:
    import fcntl

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- config ----------
# Every value can be set in CONFIG_FILE (KEY=VALUE lines) or in an environment
# variable of the same name: environment > config file > default


def default_config_file():
    if WINDOWS:
        return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'gt7-daytona', 'config.txt')
    return os.path.expanduser('~/.config/gt7-daytona.conf')


def default_cache_dir():
    if WINDOWS:
        return os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'gt7-daytona')
    return os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')))


def parse_config(path):
    values = {}
    try:
        f = open(path, encoding='utf-8-sig')
    except OSError:
        return values
    with f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].lstrip()
            key, sep, value = line.partition('=')
            if not sep:
                continue
            value = value.strip()
            if value[:1] in ('"', "'"):
                end = value.find(value[0], 1)
                value = value[1:end] if end > 0 else value[1:]
            else:
                value = re.sub(r'\s+#.*$', '', value)
            values[key.strip()] = value
    return values


DEFAULTS = {
    'KEYPRESS_LENGTH': '0.08',
    'LAP_LOG': os.path.join(os.path.expanduser('~'), 'gt7-laps.jsonl'),  # one JSON line per lap, 'off' to disable
    'LAP_MILES': '2.6',
    'LAPS': '10',
    'LOCK_FILE': os.path.join(default_cache_dir(), 'gt7-daytona.lock'),
    'LOG_FILE': os.path.join(os.path.expanduser('~'), 'gt7-daytona.log'),
    'MAINTENANCE_RACES': '20',  # remind to check the engine every N races, 0 to turn off
    'PLAYSTATION_IP': '',  # set to read GT7 telemetry: detect the start, the finish and a stuck car
    # the window lookup before each Linux key press adds ~0.04 s, the steering is tuned with it
    # included; Windows has no lookup, so its default is longer (estimate, see the readme)
    'QUICKPRESS_LENGTH': '0.05' if WINDOWS else '0.01',
    'RACE_PRIZE': '9705000',  # 1st place with clean race bonus
    'RACE_TIME': '800',  # seconds from "Race start" to the finish line, used without telemetry
    'START_TIMEOUT': '15',  # with telemetry, quit if the car isn't on track this many seconds after X
    'STUCK_SPEED': '30',  # with telemetry, km/h below which the car counts as stuck
    'STUCK_TIME': '5',  # with telemetry, quit after being stuck this many seconds
    'STRAIGHT_TIME': '15',  # seconds to drive straight after the start
    'WINDOW_NAME': r'^Chiaki \| Stream$',  # regular expression, case-insensitive
    # Key config MUST match your Chiaki key config (X11 key names; defaults are Chiaki's)
    'ANALOG_L__R': 'bracketright',  # left analog pressing right
    'DPAD_R': 'Right',
    'KEY_R2': '4',
    'KEY_X': 'Return',
    'DISPLAY': '',  # Linux only
}


def load_config(config_file=None):
    config_file = config_file or os.environ.get('CONFIG_FILE') or default_config_file()
    file_values = parse_config(config_file)
    cfg = {}
    for key, default in DEFAULTS.items():
        cfg[key] = os.environ.get(key) or file_values.get(key) or default
    cfg['CONFIG_FILE'] = config_file
    return cfg


class Config:
    """Settings with the right types; `c.RACE_TIME` etc."""

    def __init__(self, cfg):
        self.CONFIG_FILE = cfg['CONFIG_FILE']
        for key in ('LAP_MILES', 'KEYPRESS_LENGTH', 'QUICKPRESS_LENGTH'):
            setattr(self, key, float(cfg[key]))
        for key in ('LAPS', 'MAINTENANCE_RACES', 'RACE_PRIZE', 'RACE_TIME', 'START_TIMEOUT',
                    'STUCK_SPEED', 'STUCK_TIME', 'STRAIGHT_TIME'):
            setattr(self, key, int(float(cfg[key])))
        for key in ('LAP_LOG', 'LOCK_FILE', 'LOG_FILE', 'PLAYSTATION_IP', 'WINDOW_NAME', 'ANALOG_L__R',
                    'DPAD_R', 'KEY_R2', 'KEY_X', 'DISPLAY'):
            setattr(self, key, cfg[key])
        self.LOCK_FILE = os.path.expanduser(self.LOCK_FILE)
        self.LOG_FILE = os.path.expanduser(self.LOG_FILE)
        self.LAP_LOG = os.path.expanduser(self.LAP_LOG)
        if self.LAP_LOG.lower() == 'off':
            self.LAP_LOG = self.EVENT_LOG = ''
        else:  # gt7-laps.jsonl -> gt7-events.jsonl next to it
            self.EVENT_LOG = os.path.join(os.path.dirname(self.LAP_LOG), 'gt7-events.jsonl')
        self.PID_FILE = self.LOCK_FILE + '.pid'
        self.STOP_FILE = self.LOCK_FILE + '.stop'


# ---------- logging, stopping ----------


def log(*args):
    print(time.strftime('%H:%M:%S'), *args, flush=True)


class Quit(Exception):
    """Raised to leave the main loop; `code` is the exit status."""

    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


class Context:
    cfg = None


def pause(seconds):
    """Sleep that CTRL+C, `stop` and signals can interrupt at once."""
    end = time.monotonic() + seconds
    while True:
        if os.path.exists(Context.cfg.STOP_FILE):
            raise Quit(0)
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 0.1))


# ---------- keys ----------

# X11 key name -> (scan code, extended) for Windows SendInput
SCAN_CODES = {
    'Return': (0x1C, False), 'Escape': (0x01, False), 'space': (0x39, False), 'Tab': (0x0F, False),
    'BackSpace': (0x0E, False), 'bracketleft': (0x1A, False), 'bracketright': (0x1B, False),
    'comma': (0x33, False), 'period': (0x34, False), 'slash': (0x35, False), 'semicolon': (0x27, False),
    'apostrophe': (0x28, False), 'minus': (0x0C, False), 'equal': (0x0D, False),
    'Right': (0x4D, True), 'Left': (0x4B, True), 'Up': (0x48, True), 'Down': (0x50, True),
    'Shift_L': (0x2A, False), 'Control_L': (0x1D, False), 'Alt_L': (0x38, False),
}
for _i, _c in enumerate('1234567890'):
    SCAN_CODES[_c] = (0x02 + _i, False)
for _row, _start in (('qwertyuiop', 0x10), ('asdfghjkl', 0x1E), ('zxcvbnm', 0x2C)):
    for _i, _c in enumerate(_row):
        SCAN_CODES[_c] = (_start + _i, False)
        SCAN_CODES[_c.upper()] = (_start + _i, False)
for _i in range(1, 11):
    SCAN_CODES['F%d' % _i] = (0x3A + _i, False)


class KeysBase:
    def __init__(self, cfg):
        self.cfg = cfg
        self.all_keys = [cfg.ANALOG_L__R, cfg.DPAD_R, cfg.KEY_R2, cfg.KEY_X]

    def hold(self, key):
        self.send(True, key)

    def release(self, key):
        self.send(False, key)

    def press(self, key):
        self.send(True, key)
        time.sleep(self.cfg.KEYPRESS_LENGTH)
        self.send(False, key)

    def quick_press(self, key):
        self.send(True, key)
        time.sleep(self.cfg.QUICKPRESS_LENGTH)
        self.send(False, key)

    def window_lost(self):
        log('ERROR: the Chiaki stream window is gone (stream disconnected?)')
        raise Quit(1)


class X11Keys(KeysBase):
    def __init__(self, cfg):
        super().__init__(cfg)
        if cfg.DISPLAY:
            os.environ['DISPLAY'] = cfg.DISPLAY

    def check_ready(self):
        if not shutil_which('xdotool'):
            return 'xdotool is missing. Install it first (e.g. sudo apt install xdotool)'
        if not os.environ.get('DISPLAY'):
            return 'DISPLAY is not set. Run inside the desktop session or set DISPLAY (e.g. DISPLAY=:20)'
        if subprocess.run(['xdotool', 'getdisplaygeometry'], capture_output=True).returncode != 0:
            return 'Cannot open display %s' % os.environ['DISPLAY']
        return None

    def find_window(self):
        r = subprocess.run(['xdotool', 'search', '--name', self.cfg.WINDOW_NAME],
                           capture_output=True, text=True)
        ids = r.stdout.split()
        return ids[0] if ids else None

    def send(self, down, key):
        # look the window up on every key: the steering is tuned to the time this takes
        r = subprocess.run(['xdotool', 'search', '--name', self.cfg.WINDOW_NAME,
                            'keydown' if down else 'keyup', key], capture_output=True)
        if r.returncode != 0:
            self.window_lost()

    def release_all(self):
        for key in self.all_keys:
            subprocess.run(['xdotool', 'search', '--name', self.cfg.WINDOW_NAME, 'keyup', key],
                           capture_output=True)

    def is_foreground(self):
        return True


def shutil_which(cmd):
    import shutil
    return shutil.which(cmd)


class WindowsKeys(KeysBase):
    KEYEVENTF_EXTENDEDKEY = 0x1
    KEYEVENTF_KEYUP = 0x2
    KEYEVENTF_SCANCODE = 0x8
    SW_RESTORE = 9

    def __init__(self, cfg):
        super().__init__(cfg)
        from ctypes import wintypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.regex = re.compile(cfg.WINDOW_NAME, re.IGNORECASE)
        self.hwnd = None
        self.warned_focus = False

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                        ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                        ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                        ('dwExtraInfo', ctypes.c_size_t)]

        class INPUTUNION(ctypes.Union):
            _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ('u',)
            _fields_ = [('type', wintypes.DWORD), ('u', INPUTUNION)]

        self.INPUT = INPUT
        self.KEYBDINPUT = KEYBDINPUT
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

    def check_ready(self):
        for key in self.all_keys:
            if key not in SCAN_CODES:
                return 'Unknown key name %r (see SCAN_CODES in gt7_daytona.py for the supported names)' % key
        return None

    def title(self, hwnd):
        buf = ctypes.create_unicode_buffer(256)
        self.user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value

    def find_window(self):
        found = []
        wintypes = self.wintypes
        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _):
            if self.user32.IsWindowVisible(hwnd) and self.regex.search(self.title(hwnd)):
                found.append(hwnd)
            return True

        self.user32.EnumWindows(proc_type(callback), 0)
        return found[0] if found else None

    def window(self):
        if self.hwnd and self.user32.IsWindow(self.hwnd) and self.regex.search(self.title(self.hwnd)):
            return self.hwnd
        self.hwnd = self.find_window()
        if not self.hwnd:
            self.window_lost()
        return self.hwnd

    def is_foreground(self):
        return bool(self.hwnd) and self.user32.GetForegroundWindow() == self.hwnd

    def focus(self, hwnd):
        if self.user32.GetForegroundWindow() == hwnd:
            return True
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, self.SW_RESTORE)
        # a tap of Alt lets SetForegroundWindow through the foreground lock
        self.user32.keybd_event(0x12, 0, 0, 0)
        self.user32.keybd_event(0x12, 0, self.KEYEVENTF_KEYUP, 0)
        self.user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        ok = self.user32.GetForegroundWindow() == hwnd
        if not ok and not self.warned_focus:
            log('WARNING: could not bring the Chiaki window to the front; keys may go elsewhere')
            self.warned_focus = True
        return ok

    def _input(self, down, key):
        scan, extended = SCAN_CODES[key]
        flags = self.KEYEVENTF_SCANCODE
        if extended:
            flags |= self.KEYEVENTF_EXTENDEDKEY
        if not down:
            flags |= self.KEYEVENTF_KEYUP
        inp = self.INPUT(type=1)
        inp.ki = self.KEYBDINPUT(0, scan, flags, 0, 0)
        self.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(self.INPUT))

    def send(self, down, key):
        hwnd = self.window()
        if down:  # keys held by a key-up alone don't need the focus; a press does
            self.focus(hwnd)
        self._input(down, key)

    def release_all(self):
        for key in self.all_keys:
            self._input(False, key)


def make_keys(cfg):
    return WindowsKeys(cfg) if WINDOWS else X11Keys(cfg)


# ---------- telemetry ----------

KEY = b'Simulator Interface Packet GT7 ver 0.0'[:32]
SEND_PORT = 33739
RECEIVE_PORT = 33740


def rotl(v, c):
    return ((v << c) & 0xffffffff) | (v >> (32 - c))


def salsa20_block(key, nonce, counter):
    c = struct.unpack('<4I', b'expand 32-byte k')
    k = struct.unpack('<8I', key)
    n = struct.unpack('<2I', nonce)
    state = [c[0], k[0], k[1], k[2], k[3], c[1], n[0], n[1],
             counter & 0xffffffff, counter >> 32, c[2], k[4], k[5], k[6], k[7], c[3]]
    x = state[:]
    for _ in range(10):
        for a, b, cc, d in ((0, 4, 8, 12), (5, 9, 13, 1), (10, 14, 2, 6), (15, 3, 7, 11),
                            (0, 1, 2, 3), (5, 6, 7, 4), (10, 11, 8, 9), (15, 12, 13, 14)):
            x[b] ^= rotl((x[a] + x[d]) & 0xffffffff, 7)
            x[cc] ^= rotl((x[b] + x[a]) & 0xffffffff, 9)
            x[d] ^= rotl((x[cc] + x[b]) & 0xffffffff, 13)
            x[a] ^= rotl((x[d] + x[cc]) & 0xffffffff, 18)
    return struct.pack('<16I', *[(x[i] + state[i]) & 0xffffffff for i in range(16)])


def decrypt(data):
    iv1 = int.from_bytes(data[0x40:0x44], 'little')
    nonce = (iv1 ^ 0xDEADBEAF).to_bytes(4, 'little') + iv1.to_bytes(4, 'little')
    stream = b''.join(salsa20_block(KEY, nonce, i) for i in range((len(data) + 63) // 64))
    packet = bytes(a ^ b for a, b in zip(data, stream))
    if len(packet) < 0x94 or struct.unpack_from('<I', packet, 0)[0] != 0x47375330:
        return None
    return packet


class State:
    __slots__ = ('time', 'on_track', 'paused', 'loading', 'lap', 'laps', 'speed', 'position', 'best', 'last',
                 'x', 'z')


def parse_state(p, now=None):
    s = State()
    flags = struct.unpack_from('<H', p, 0x8E)[0]
    s.lap, s.laps = struct.unpack_from('<hh', p, 0x74)
    s.best, s.last = struct.unpack_from('<ii', p, 0x78)
    s.position = struct.unpack_from('<h', p, 0x84)[0]
    s.speed = int(struct.unpack_from('<f', p, 0x4C)[0] * 3.6)
    s.x, s.z = struct.unpack_from('<f', p, 0x04)[0], struct.unpack_from('<f', p, 0x0C)[0]
    s.on_track = flags & 1
    s.paused = flags >> 1 & 1
    s.loading = flags >> 2 & 1
    s.time = time.time() if now is None else now
    return s


class Recorder:
    """Appends one JSON line per finished lap (LAP_LOG) and, on an error, the last
    ~10 s of states (EVENT_LOG), so a person or an LLM can read the run afterwards."""

    def __init__(self, lap_log, event_log):
        self.lap_log = lap_log
        self.event_log = event_log
        self.race = 0
        self.ring = collections.deque(maxlen=50)  # states arrive every 0.2 s
        self.lock = threading.Lock()
        self.begin(0)

    def begin(self, race):
        with self.lock:
            self.race = race
            self.prev_lap = 0
            self.vmax = 0
            self.vmin = None
            self.ring.clear()

    def write(self, path, row):
        if not path:
            return
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row, separators=(',', ':')) + '\n')
        except OSError:
            pass  # recording must never stop the farm

    def feed(self, s):
        if not s.on_track or s.paused or s.loading:
            return
        with self.lock:
            self.ring.append((round(s.time, 1), s.lap, s.speed, round(s.x), round(s.z)))
            if s.lap > self.prev_lap >= 1:
                self.write(self.lap_log, {
                    'kind': 'lap', 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'race': self.race,
                    'lap': self.prev_lap, 'lap_ms': s.last, 'best_ms': s.best, 'pos': s.position,
                    'vmax': self.vmax, 'vmin': self.vmin})
                self.vmax, self.vmin = 0, None
            self.prev_lap = s.lap if s.lap >= 1 else 0
            if s.lap >= 1:
                self.vmax = max(self.vmax, s.speed)
                self.vmin = s.speed if self.vmin is None else min(self.vmin, s.speed)

    def event(self, reason):
        with self.lock:
            self.write(self.event_log, {
                'kind': 'event', 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'race': self.race,
                'reason': reason, 'tail': [list(r) for r in self.ring]})  # time, lap, km/h, x, z


class Telemetry:
    """Receives GT7 telemetry in a thread. GT7 only sends to a host that keeps
    sending it heartbeats. The host firewall must allow UDP port 33740 in."""

    def __init__(self, host, recorder=None):
        self.host = host
        self.recorder = recorder
        self.state = None
        self.stop = False
        self.error = None
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(('0.0.0.0', RECEIVE_PORT))
            self.sock.settimeout(1)
        except OSError as e:
            self.sock = None
            self.error = str(e)
            return
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        last_heartbeat = last_parse = 0
        while not self.stop:
            now = time.time()
            if now - last_heartbeat > 5:
                try:
                    self.sock.sendto(b'A', (self.host, SEND_PORT))
                except OSError:
                    pass
                last_heartbeat = now
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                time.sleep(0.5)
                continue
            if now - last_parse < 0.2:
                continue
            packet = decrypt(data)
            if packet is None:
                continue
            self.state = parse_state(packet)
            if self.recorder:
                try:
                    self.recorder.feed(self.state)
                except Exception:
                    pass
            last_parse = now

    def latest(self):
        """The newest state, or None without fresh data."""
        s = self.state
        if s is not None and time.time() - s.time <= 2:
            return s
        return None

    def close(self):
        self.stop = True
        if self.sock:
            self.sock.close()


def lap_time(ms):
    return '%d:%06.3f' % (ms // 60000, (ms % 60000) / 1000)


# ---------- process management ----------


def acquire_lock(cfg):
    """Take the single-instance lock; returns the open file, or None if taken."""
    os.makedirs(os.path.dirname(cfg.LOCK_FILE) or '.', exist_ok=True)
    f = open(cfg.LOCK_FILE, 'a+b')
    try:
        if WINDOWS:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def running_pid(cfg):
    lock = acquire_lock(cfg)
    if lock:
        lock.close()  # releases it
        return None
    try:
        with open(cfg.PID_FILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def prevent_sleep():
    if WINDOWS:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x1)  # CONTINUOUS | SYSTEM_REQUIRED


def tail(path, n):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return ''.join(f.readlines()[-n:])
    except OSError:
        return ''


def cmd_start(cfg, args):
    pid = running_pid(cfg)
    if pid is not None:
        print('Already running (pid %s)' % pid)
        return 1
    cmd = [sys.executable, os.path.abspath(__file__), 'run', '--yes']
    if args.ip:
        cmd += ['--ip', args.ip]
    os.makedirs(os.path.dirname(cfg.LOG_FILE) or '.', exist_ok=True)
    out = open(cfg.LOG_FILE, 'ab')
    kwargs = {}
    if WINDOWS:
        kwargs['creationflags'] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kwargs['start_new_session'] = True
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out, **kwargs)
    time.sleep(2)
    print(tail(cfg.LOG_FILE, 5), end='')
    return 0


def cmd_stop(cfg):
    pid = running_pid(cfg)
    if pid is None:
        print('Not running')
        return 0
    open(cfg.STOP_FILE, 'w').close()  # the script polls for it and releases its keys
    for _ in range(100):
        if running_pid(cfg) is None:
            print('Stopped')
            return 0
        time.sleep(0.1)
    print('Still running (pid %s)' % pid)
    return 1


def cmd_status(cfg):
    pid = running_pid(cfg)
    print('Not running' if pid is None else 'Running (pid %s)' % pid)
    print(tail(cfg.LOG_FILE, 5), end='')
    return 0


# ---------- check ----------


def cmd_check(cfg, keys):
    ok_all = True

    def report(ok, text, fix=''):
        nonlocal ok_all
        print(('  [OK]  ' if ok else '  [NG]  ') + text)
        if not ok:
            ok_all = False
            if fix:
                print('        -> ' + fix)

    print('Python %s on %s' % (sys.version.split()[0], 'Windows' if WINDOWS else 'Linux'))
    print('Config file: %s (%s)' % (cfg.CONFIG_FILE, 'found' if os.path.exists(cfg.CONFIG_FILE) else 'not found, using defaults'))
    problem = keys.check_ready()
    report(problem is None, 'Key sending is ready' if problem is None else problem)
    if problem is None:
        w = keys.find_window()
        report(bool(w), 'Chiaki stream window found' if w else 'Chiaki stream window not found',
               'Start Chiaki and connect to your PlayStation until the stream shows. '
               'If the title differs, set WINDOW_NAME (a regular expression).')
        if w and WINDOWS:
            keys.hwnd = w
            keys.focus(w)
            report(keys.is_foreground(), 'Chiaki window can be brought to the front',
                   'Close windows that stay on top, or click the Chiaki window and run again.')
    if cfg.PLAYSTATION_IP:
        tel = Telemetry(cfg.PLAYSTATION_IP)
        if tel.error:
            report(False, 'Cannot listen on UDP %d: %s' % (RECEIVE_PORT, tel.error),
                   'Another program (or a second copy of this script) uses the port.')
        else:
            print('  ...   waiting up to 10 s for telemetry from %s (start a race or sit in the menu)' % cfg.PLAYSTATION_IP)
            for _ in range(100):
                if tel.latest():
                    break
                time.sleep(0.1)
            report(tel.latest() is not None, 'Telemetry received from %s' % cfg.PLAYSTATION_IP,
                   'Check PLAYSTATION_IP, that GT7 is running, and that UDP port %d is allowed in the firewall.%s' % (
                       RECEIVE_PORT,
                       ' In an administrator prompt: netsh advfirewall firewall add rule name="GT7 telemetry" '
                       'dir=in action=allow protocol=UDP localport=%d' % RECEIVE_PORT if WINDOWS else
                       ' e.g. sudo ufw allow from %s to any port %d proto udp' % (cfg.PLAYSTATION_IP, RECEIVE_PORT)))
            tel.close()
    else:
        print('  ...   PLAYSTATION_IP is not set: telemetry is off and races are timed with RACE_TIME')
    print('Key names (must match the key config in Chiaki): X=%s R2=%s Right=%s steer=%s' % (
        cfg.KEY_X, cfg.KEY_R2, cfg.DPAD_R, cfg.ANALOG_L__R))
    print('All checks passed.' if ok_all else 'Some checks failed.')
    return 0 if ok_all else 1


# ---------- the race loop ----------


def race_loop(cfg, keys, tel):
    race_miles = '%.1f' % (cfg.LAP_MILES * cfg.LAPS)
    current_miles = 0.0
    current_money = 0
    race_count = 0
    clock = time.monotonic

    while True:
        race_count += 1
        log('Race %d' % race_count)
        if tel and tel.recorder:
            tel.recorder.begin(race_count)
        if race_count == 1:
            # the start screen hides its menu after a while without input, and the
            # first X only brings it back; if the menu was showing, this X starts the
            # race and the next one lands on the loading screen
            keys.press(cfg.KEY_X)
            pause(2)
        keys.press(cfg.KEY_X)
        pause(2)
        keys.hold(cfg.KEY_R2)  # hold only during the race, never in the menus
        pause(6)

        start_deadline = clock() + cfg.START_TIMEOUT - 8
        while tel and tel.latest() and tel.latest().on_track == 0:
            if clock() >= start_deadline:
                log('ERROR: the race did not start (telemetry: the car is not on track)')
                if tel.recorder:
                    tel.recorder.event('start')
                raise Quit(1)
            pause(0.5)

        if tel and tel.latest():
            log('  Race start (telemetry: Race ending at the finish line)')
        else:
            log('  Race start (Race ending at %s)' % time.strftime('%H:%M:%S', time.localtime(time.time() + cfg.RACE_TIME)))
        # time by wall clock: each key press adds overhead, so counting ticks drifts
        steer_start = clock() + cfg.STRAIGHT_TIME
        race_end = clock() + cfg.RACE_TIME
        slow_since = None
        result = ''
        while True:
            t = tel.latest() if tel else None
            if t:
                if t.laps > 0 and t.lap > t.laps:
                    result = ' (P%d, best lap %s)' % (t.position, lap_time(t.best))
                    break
                if (not t.paused and t.speed < cfg.STUCK_SPEED
                        and (t.lap >= 1 or clock() >= steer_start)):
                    slow_since = slow_since if slow_since is not None else clock()
                    if clock() - slow_since >= cfg.STUCK_TIME:
                        log('ERROR: the car is stuck (lap %d, %d km/h for %ds)' % (t.lap, t.speed, cfg.STUCK_TIME))
                        if tel.recorder:
                            tel.recorder.event('stuck')
                        raise Quit(1)
                else:
                    slow_since = None
                if clock() >= race_end + 120:
                    log('ERROR: no finish after %ds (lap %d of %d)' % (cfg.RACE_TIME + 120, t.lap, t.laps))
                    if tel.recorder:
                        tel.recorder.event('no finish')
                    raise Quit(1)
            elif clock() >= race_end:
                break
            if clock() >= steer_start:
                keys.quick_press(cfg.ANALOG_L__R)
            pause(0.5)

        log('  Race ending%s' % result)
        pause(30)
        keys.release(cfg.KEY_R2)

        log('Standings')
        pause(20)  # extra wait here to buffer for slow finishes
        keys.press(cfg.KEY_X)

        log('Rewards')
        keys.press(cfg.KEY_X)
        pause(3)

        current_miles += float(race_miles)
        current_money += cfg.RACE_PRIZE

        log('  Credits: {:,}'.format(current_money))
        keys.press(cfg.KEY_X)
        pause(2)

        log('  Miles: %.1f' % current_miles)
        keys.press(cfg.KEY_X)
        pause(4)

        log('Replay')
        keys.press(cfg.KEY_X)
        pause(4)
        keys.press(cfg.KEY_X)
        pause(2)
        keys.press(cfg.KEY_X)
        keys.press(cfg.KEY_X)
        pause(5)

        log('Retry')
        keys.press(cfg.DPAD_R)
        pause(1)
        keys.press(cfg.KEY_X)
        pause(4)

        if cfg.MAINTENANCE_RACES > 0 and race_count % cfg.MAINTENANCE_RACES == 0:
            log('  %d races done: check the oil and engine condition' % race_count)


def cmd_run(cfg, keys, assume_yes):
    problem = keys.check_ready()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    lock = acquire_lock(cfg)
    if not lock:
        print('gt7_daytona.py is already running (pid %s). Quitting' % running_pid(cfg), file=sys.stderr)
        return 1
    window = keys.find_window()
    if not window:
        print('The Chiaki stream window was not found. Start Chiaki and connect first '
              '(run `gt7_daytona.py check` to test the setup). Quitting', file=sys.stderr)
        return 1
    if not assume_yes and sys.stdin.isatty():
        print('Put the arrow on the Start button in the race menu, then press Enter to begin (CTRL+C to cancel).')
        if WINDOWS:
            print('The script will bring the Chiaki window to the front and keep it there; leave the PC alone while it runs.')
        input()

    with open(cfg.PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    try:
        os.remove(cfg.STOP_FILE)
    except OSError:
        pass
    prevent_sleep()

    def on_signal(signum, _frame):
        raise Quit(128 + signum)

    for name in ('SIGHUP', 'SIGTERM', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)

    tel = None
    code = 0
    try:
        log('Started: RACE_TIME=%d STRAIGHT_TIME=%d RACE_PRIZE=%d window=%s' % (
            cfg.RACE_TIME, cfg.STRAIGHT_TIME, cfg.RACE_PRIZE, window))
        if cfg.PLAYSTATION_IP:
            rec = Recorder(cfg.LAP_LOG, cfg.EVENT_LOG) if cfg.LAP_LOG else None
            tel = Telemetry(cfg.PLAYSTATION_IP, rec)
            for _ in range(10):
                if tel.latest():
                    break
                pause(1)
            if tel.latest():
                log('Telemetry from %s' % cfg.PLAYSTATION_IP)
            else:
                log('WARNING: no telemetry from %s (is UDP port %d open?); timing the race with RACE_TIME' % (
                    cfg.PLAYSTATION_IP, RECEIVE_PORT))
        race_loop(cfg, keys, tel)
    except Quit as q:
        code = q.code
    except KeyboardInterrupt:
        code = 130
    finally:
        try:
            keys.release_all()
        except Exception:
            pass
        if tel:
            tel.close()
        for path in (cfg.PID_FILE, cfg.STOP_FILE):
            try:
                os.remove(path)
            except OSError:
                pass
        log('Quitting')
        lock.close()
    return code


def main():
    ap = argparse.ArgumentParser(description='Gran Turismo 7 Daytona autopilot')
    ap.add_argument('command', nargs='?', default='run',
                    choices=['run', 'start', 'stop', 'status', 'log', 'check'])
    ap.add_argument('lines', nargs='?', type=int, default=30, help='lines for `log`')
    ap.add_argument('--yes', '-y', action='store_true', help="don't wait for Enter before starting")
    ap.add_argument('--ip', help='PlayStation IP address (PLAYSTATION_IP)')
    ap.add_argument('--config', help='config file (CONFIG_FILE)')
    args = ap.parse_args()

    values = load_config(args.config)
    if args.ip:
        values['PLAYSTATION_IP'] = args.ip
    cfg = Config(values)
    Context.cfg = cfg

    if args.command == 'start':
        return cmd_start(cfg, args)
    if args.command == 'stop':
        return cmd_stop(cfg)
    if args.command == 'status':
        return cmd_status(cfg)
    if args.command == 'log':
        print(tail(cfg.LOG_FILE, args.lines), end='')
        return 0
    keys = make_keys(cfg)
    if args.command == 'check':
        return cmd_check(cfg, keys)
    return cmd_run(cfg, keys, args.yes)


if __name__ == '__main__':
    sys.exit(main())
