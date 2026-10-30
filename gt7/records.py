# Clearing out the recordings: the screenshots in SCREEN_RECORD/<YYYYmmdd-HHMMSS>/ and the
# telemetry in TELEMETRY_RECORD/<YYYYmmdd-HHMMSS>.gt7tel grow by about 100 MB a race. Only
# names in exactly that form are removed: rename a recording to keep it.

import os
import re
import shutil
import time

NAME = re.compile(r'\d{8}-\d{6}(\.gt7tel)?$')


def prune(folder, hours, keep=(), now=None):
    """Remove the recordings in `folder` last changed more than `hours` ago, except `keep`
    (paths). Returns how many were removed and the bytes freed."""
    if not folder or hours <= 0 or not os.path.isdir(folder):
        return 0, 0
    now, keep = now or time.time(), {os.path.abspath(k) for k in keep if k}
    removed = freed = 0
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not NAME.match(name) or os.path.abspath(path) in keep:
            continue
        if name.endswith('.gt7tel') != os.path.isfile(path):
            continue  # a .gt7tel that is not a file, or a dated name that is not a folder
        try:
            if now - os.path.getmtime(path) <= hours * 3600:
                continue
            if os.path.isdir(path):
                size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)
                shutil.rmtree(path)
            else:
                size = os.path.getsize(path)
                os.remove(path)
        except OSError:
            continue
        removed, freed = removed + 1, freed + size
    return removed, freed


def free_gb(path):
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return None
