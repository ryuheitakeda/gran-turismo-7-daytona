# Read the course map at the top right of the race HUD: where our car (the red
# marker) and the other cars (blue markers) are, and whether one is close ahead.
# The map is about 12 m a pixel at 1280x720.

import math

BOX = (1030, 10, 160, 170)  # x, y, width, height of the map on the screen
METRES_PER_PIXEL = 12.0


def markers(image):
    """(own, others): our marker's (x, y) or None, and a list of (x, y, pixels) blobs
    of the other cars' markers, in screen pixels."""
    width, height, rgb = image
    x0, y0, w, h = BOX
    red, blue = [], set()
    for y in range(y0, min(y0 + h, height)):
        base = (y * width + x0) * 3
        row = rgb[base:base + w * 3]
        for i in range(0, len(row), 3):
            r, g, b = row[i], row[i + 1], row[i + 2]
            if r - max(g, b) > 50:
                red.append((x0 + i // 3, y))
            elif b - max(r, g) > 50:
                blue.add((x0 + i // 3, y))
    own = None
    if red:
        own = (sum(p[0] for p in red) / len(red), sum(p[1] for p in red) / len(red))
    blobs = []
    while blue:  # connected pixels (8 neighbours) make one blob
        stack = [blue.pop()]
        pts = []
        while stack:
            x, y = stack.pop()
            pts.append((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in blue:
                        blue.remove(q)
                        stack.append(q)
        if len(pts) >= 2:
            blobs.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), len(pts)))
    return own, blobs


class Traffic:
    """Tell, from one map reading after another, whether another car is close ahead:
    within `within` metres of ours, in the direction we are moving on the map."""

    def __init__(self, within=200.0):
        self.within = within
        self.last_own = None
        self.heading = None  # unit vector of our motion on the map

    def update(self, image):
        """(distance in metres to the nearest car ahead, or None; number of cars on the map)."""
        own, blobs = markers(image)
        if own is None:
            return None, len(blobs)
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
