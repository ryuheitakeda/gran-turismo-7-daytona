# Read the course map at the top right of the race HUD: where our car (the red
# marker) and the other cars (blue markers) are, and whether one is close ahead.
# The map is about 12 m a pixel at 1280x720.

import math

BOX = (1030, 10, 160, 170)  # x, y, width, height of the map on the screen
METRES_PER_PIXEL = 12.0


def blobs_of(points):
    """Connected groups (8 neighbours) of a set of (x, y): [(x, y, pixels, [points])]."""
    points = set(points)
    out = []
    while points:
        stack = [points.pop()]
        pts = []
        while stack:
            x, y = stack.pop()
            pts.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in points:
                        points.remove(q)
                        stack.append(q)
        out.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), len(pts), pts))
    return out


def markers(image, last_own=None):
    """(own, others): our marker's (x, y) or None, and the other cars' markers as
    [(x, y, pixels)] blobs, in screen pixels. Billboards behind the map can be red
    or blue too, so ours must be a small red blob (with last_own, the one nearest
    to it, and no further than 25 pixels), and the others' blobs the markers'
    light blue."""
    width, height, rgb = image
    x0, y0, w, h = BOX
    red, blue = set(), set()
    for y in range(y0, min(y0 + h, height)):
        base = (y * width + x0) * 3
        row = rgb[base:base + w * 3]
        for i in range(0, len(row), 3):
            r, g, b = row[i], row[i + 1], row[i + 2]
            if r >= 110 and r - max(g, b) > 35:  # our marker is pink where the background is bright
                red.add((x0 + i // 3, y))
            elif b > 200 and g > 140 and b - r > 50:  # the markers' light blue, not a billboard's
                blue.add((x0 + i // 3, y))


    # our marker is a small blob (a billboard behind the map is a huge one); it covers
    # the track line, so it can't be told by being next to it
    reds = [b for b in blobs_of(red) if 2 <= b[2] <= 150]
    own = None
    if reds:
        if last_own:
            own = min(reds, key=lambda b: math.hypot(b[0] - last_own[0], b[1] - last_own[1]))
            if math.hypot(own[0] - last_own[0], own[1] - last_own[1]) > 25:
                own = None  # too far from a second ago: a billboard, not the marker
        else:
            own = max(reds, key=lambda b: b[2])
    blues = [b[:3] for b in blobs_of(blue) if 2 <= b[2] <= 400]
    return (own and own[:2]), blues


class Traffic:
    """Tell, from one map reading after another, whether another car is close ahead:
    within `within` metres of ours, in the direction we are moving on the map."""

    def __init__(self, within=200.0):
        self.within = within
        self.last_own = None
        self.misses = 0  # readings in a row without our marker
        self.heading = None  # unit vector of our motion on the map

    def update(self, image):
        """(distance in metres to the nearest car ahead, or None; number of cars on the map)."""
        own, blobs = markers(image, self.last_own)
        if own is None:
            self.misses += 1
            if self.misses >= 3:  # a billboard hid it, or it moved on: pick afresh next time
                self.last_own = None
            return None, len(blobs)
        self.misses = 0
        if self.last_own:
            dx, dy = own[0] - self.last_own[0], own[1] - self.last_own[1]
            if math.hypot(dx, dy) >= 2:
                n = math.hypot(dx, dy)
                self.heading = (dx / n, dy / n)
        self.last_own = own
        nearest = None
        if self.heading:
            for bx, by, size in blobs:
                vx, vy = bx - own[0], by - own[1]
                along = vx * self.heading[0] + vy * self.heading[1]
                across = abs(vx * self.heading[1] - vy * self.heading[0])
                if along > 0 and across < 8 and along * METRES_PER_PIXEL <= self.within:
                    metres = along * METRES_PER_PIXEL
                    if nearest is None or metres < nearest:
                        nearest = metres
        return nearest, len(blobs)
