# Contacts: a sudden drop in speed that neither the throttle nor the air explains. Nitrous
# running out or the banking costs about 5 m/s^2; the car that ran into another on the back
# straight lost 17.7 km/h in 0.14 s, about 35 m/s^2 (2026-10-30 16:33:34, #29).

import collections

DECEL = 20.0  # m/s^2 over WINDOW seconds
WINDOW = 0.15
MIN_SPEED = 80.0  # km/h: not the launch, nor a car already stopped
QUIET = 3.0  # seconds after one before the next counts


class Detector:
    def __init__(self, decel=DECEL, window=WINDOW):
        self.decel, self.window = decel, window
        self.samples = collections.deque()
        self.last = -1e9

    def reset(self):
        self.samples.clear()

    def update(self, when, speed):
        """Feed one packet (seconds, km/h); the deceleration in m/s^2 when it is a contact."""
        self.samples.append((when, speed))
        while self.samples and when - self.samples[0][0] > self.window:
            self.samples.popleft()
        then, before = self.samples[0]
        if when - then < self.window * 0.6 or before < MIN_SPEED:
            return None
        rate = (before - speed) / 3.6 / (when - then)
        if rate >= self.decel and when - self.last >= QUIET:
            self.last = when
            return rate
        return None
