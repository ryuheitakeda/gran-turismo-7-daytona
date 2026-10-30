# Steering by the telemetry: where the car is across the track, and how much to
# steer to stay on a line.
#
# The line is the wall line the car has been riding (it repeats to within a
# few centimetres every lap), built from a recording by gt7-analyze.py track and
# kept in ~/.config/gt7-daytona/track.json. Every packet (60 a second) the car's
# position is projected onto it: d is how far it is towards the outside wall
# (+, metres) and psi how much its heading points that way (+, radians).

import json
import math
import os

TRACK = os.environ.get('TRACK', os.path.expanduser('~/.config/gt7-daytona/track.json'))
SPACING = 2.0  # metres between the line's points


def build(laps):
    """The line from one lap of samples (dicts from gt7.telemetry.parse), a point
    every SPACING metres, with the sign that makes +d the outside of the oval."""
    pts = [(s['position'][0], s['position'][2]) for s in laps]
    line, carry = [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        step = math.dist(a, b)
        while carry + step >= SPACING and step > 0:
            u = (SPACING - carry) / step
            a = (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))
            line.append(a)
            step, carry = math.dist(a, b), 0.0
        carry += step
    cx = sum(p[0] for p in line) / len(line)
    cz = sum(p[1] for p in line) / len(line)
    # on a closed loop the centre is inside: make d positive away from it
    a, b = line[0], line[1]
    side = (b[0] - a[0]) * (cz - a[1]) - (b[1] - a[1]) * (cx - a[0])
    return {'points': [[round(x, 3), round(z, 3)] for x, z in line], 'outside': -1 if side > 0 else 1}


class Track:
    def __init__(self, data):
        self.points = [tuple(p) for p in data['points']]
        self.outside = data['outside']
        self.n = len(self.points)
        # how sharply the line bends towards the inside at each point (1/m), over +-20 m
        n, pts, w = self.n, self.points, 10
        head = [math.atan2(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1]) for i in range(n)]
        inside = 1 if sum(wrap(head[(i + 1) % n] - head[i]) for i in range(n)) > 0 else -1
        self.curvature = [inside * wrap(head[(i + w) % n] - head[(i - w) % n]) / (2 * w * SPACING)
                          for i in range(n)]
        self.sharpest = max(self.curvature) or 1.0

    @classmethod
    def load(cls, path=TRACK):
        with open(path) as f:
            return cls(json.load(f))

    def _segment(self, i, x, z):
        a, b = self.points[i % self.n], self.points[(i + 1) % self.n]
        dx, dz = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dz * dz or 1e-9
        u = max(0.0, min(1.0, ((x - a[0]) * dx + (z - a[1]) * dz) / length2))
        px, pz = a[0] + u * dx, a[1] + u * dz
        side = dx * (z - a[1]) - dz * (x - a[0])
        d = math.hypot(x - px, z - pz) * (1 if side > 0 else -1) * self.outside
        return (x - px) ** 2 + (z - pz) ** 2, d, math.atan2(dx, dz)

    def project(self, x, z, hint=None):
        """(index, d, heading of the line) for a position; searches near the hint."""
        span = range(hint - 30, hint + 30) if hint is not None else range(self.n)
        best = min(((self._segment(i, x, z), i) for i in span), key=lambda c: c[0][0])
        (_, d, heading), i = best
        return i % self.n, d, heading


def wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


class LineDriver:
    """Left stick from -1 (left) to 1 (right) that keeps the car gap metres inside the
    wall line, heading along it. Steering right is towards the outside wall. With
    curve, it also steers left by up to that much where the line bends (ahead
    metres on), so the tyres take more of the turn and the wall less."""

    def __init__(self, track, gap=0.3, kd=0.1, kpsi=1.0, limit=0.3, curve=0.0, ahead=30.0):
        self.track, self.gap, self.kd, self.kpsi, self.limit = track, gap, kd, kpsi, limit
        self.curve, self.ahead = curve, int(ahead / SPACING)
        self.hint = None
        self.d = self.psi = self.stick = 0.0

    def update(self, t):
        x, z = t['position'][0], t['position'][2]
        vx, vz = t['velocity'][0], t['velocity'][2]
        if self.hint is None or abs(self.d) > 20:
            self.hint = None  # lost (a new race, a reset): search the whole line
        self.hint, self.d, heading = self.track.project(x, z, self.hint)
        if math.hypot(vx, vz) > 3:
            self.psi = wrap(math.atan2(vx, vz) - heading) * -self.track.outside
        error = self.d + self.gap  # + when nearer the wall than wanted
        bend = max(0.0, self.track.curvature[(self.hint + self.ahead) % self.track.n]) / self.track.sharpest
        stick = -(self.kd * error + self.kpsi * self.psi) - self.curve * bend
        self.stick = max(-self.limit, min(self.limit, stick))
        return self.stick
