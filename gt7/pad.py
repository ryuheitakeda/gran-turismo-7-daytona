# A virtual gamepad (Linux uinput) that Chiaki reads like a real one, so the
# script can send analog stick and trigger values instead of keys
#
# It has the layout of an Xbox 360 pad, which SDL (and so Chiaki) knows:
# A = cross, B = circle, X = square, Y = triangle, START = OPTIONS. Chiaki adds
# its state to the keyboard's, so the keys keep working. The kernel removes the
# pad when the process ends, even on kill -9, so nothing stays pressed.
# Chiaki can only open the pad with the udev rule in 70-gt7-pad.rules.

import fcntl
import os
import struct
import sys
import time

NAME = 'GT7 Autopilot Pad'

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_ABSBIT = 0x40045564, 0x40045565, 0x40045567
UI_DEV_SETUP, UI_ABS_SETUP = 0x405c5503, 0x401c5504
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
UI_GET_SYSNAME_64 = 0x8040552c
BUS_USB, VENDOR, PRODUCT, VERSION = 0x03, 0x045e, 0x028e, 0x0114  # Xbox 360 pad

BUTTONS = {'cross': 0x130, 'circle': 0x131, 'square': 0x133, 'triangle': 0x134,
           'l1': 0x136, 'r1': 0x137, 'share': 0x13a, 'options': 0x13b, 'ps': 0x13c,
           'l3': 0x13d, 'r3': 0x13e}
DPAD = {'up': (0x11, -1), 'down': (0x11, 1), 'left': (0x10, -1), 'right': (0x10, 1)}
STICKS = (0x00, 0x01, 0x03, 0x04)  # left x, left y, right x, right y
L2, R2 = 0x02, 0x05


def event(kind, code, value):
    return struct.pack('<qqHHi', 0, 0, kind, code, value)


class Pad:
    def __init__(self, name=NAME):
        self.fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
        try:
            for kind in (EV_KEY, EV_ABS):
                fcntl.ioctl(self.fd, UI_SET_EVBIT, kind)
            for code in BUTTONS.values():
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            axes = [(code, -32768, 32767) for code in STICKS] + \
                   [(L2, 0, 255), (R2, 0, 255), (0x10, -1, 1), (0x11, -1, 1)]
            for code, low, high in axes:
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, code)
                fcntl.ioctl(self.fd, UI_ABS_SETUP, struct.pack('<H2x6i', code, 0, low, high, 0, 0, 0))
            fcntl.ioctl(self.fd, UI_DEV_SETUP, struct.pack(
                '<4H80sI', BUS_USB, VENDOR, PRODUCT, VERSION, name.encode(), 0))
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise

    def send(self, *changes):
        """Apply (kind, code, value) changes at once."""
        os.write(self.fd, b''.join(event(*c) for c in changes) + event(EV_SYN, 0, 0))

    def button(self, name, down):
        if name in DPAD:
            code, value = DPAD[name]
            self.send((EV_ABS, code, value if down else 0))
        else:
            self.send((EV_KEY, BUTTONS[name], int(down)))

    def press(self, name, seconds=0.08):
        self.button(name, True)
        time.sleep(seconds)
        self.button(name, False)

    def stick(self, x, y=0.0):
        """Left stick, -1 (left/up) to 1 (right/down)."""
        self.send((EV_ABS, STICKS[0], round(max(-1, min(1, x)) * 32767)),
                  (EV_ABS, STICKS[1], round(max(-1, min(1, y)) * 32767)))

    def r2(self, value):
        """0 (released) to 1 (fully pressed)."""
        self.send((EV_ABS, R2, round(max(0, min(1, value)) * 255)))

    def neutral(self):
        self.send(*[(EV_KEY, code, 0) for code in BUTTONS.values()],
                  *[(EV_ABS, code, 0) for code in STICKS + (L2, R2, 0x10, 0x11)])

    def device(self):
        """The pad's /dev/input/event* node."""
        sysname = fcntl.ioctl(self.fd, UI_GET_SYSNAME_64, bytes(64)).split(b'\0')[0].decode()
        base = '/sys/devices/virtual/input/' + sysname
        for entry in sorted(os.listdir(base)):
            if entry.startswith('event'):
                return '/dev/input/' + entry
        return None

    def close(self):
        if self.fd is not None:
            try:
                self.neutral()
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            finally:
                os.close(self.fd)
                self.fd = None


class DryPad:
    """Stands in for Pad in tests: logs instead of creating a device."""

    def __init__(self, name=NAME, out=sys.stderr):
        self.out = out

    def _log(self, text):
        print('pad: ' + text, file=self.out, flush=True)

    def button(self, name, down):
        if name not in DPAD and name not in BUTTONS:
            raise KeyError(name)
        self._log('%s %s' % (name, 'down' if down else 'up'))

    def press(self, name, seconds=0.08):
        self.button(name, True)
        time.sleep(seconds)
        self.button(name, False)

    def stick(self, x, y=0.0):
        self._log('stick %.3f %.3f' % (x, y))

    def r2(self, value):
        self._log('r2 %.2f' % value)

    def neutral(self):
        self._log('neutral')

    def device(self):
        return None

    def close(self):
        self._log('closed')


def opened_by(device, program='chiaki'):
    """Pids of the running program that have the device open."""
    pids = []
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            if open('/proc/%s/comm' % pid).read().strip() != program:
                continue
            fds = os.listdir('/proc/%s/fd' % pid)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink('/proc/%s/fd/%s' % (pid, fd)) == device:
                    pids.append(int(pid))
                    break
            except OSError:
                pass
    return pids
