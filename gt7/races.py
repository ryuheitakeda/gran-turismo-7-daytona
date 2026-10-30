# The record of races: one JSON line per race in ~/gt7-races.jsonl (RACES_FILE),
# and {"maintenance": time} lines for when the oil or the engine was seen to.
# The median lap of a race against those after the last maintenance tells how
# far the engine has worn.

import datetime
import json
import os
import statistics

RACES_FILE = os.environ.get('RACES_FILE', os.path.expanduser('~/gt7-races.jsonl'))
WINDOW = 5  # races for the baseline after a maintenance, and for "now"


def append(record, path=RACES_FILE):
    with open(path, 'a') as f:
        f.write(json.dumps(record) + '\n')


def load(path=RACES_FILE):
    records = []
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return records
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            pass
    return records


def since_maintenance(records):
    last = max((i for i, r in enumerate(records) if 'maintenance' in r), default=-1)
    return [r for r in records[last + 1:] if 'maintenance' not in r]


def wear(records, drive):
    """How the median laps of the last WINDOW races driven this way compare with
    the first WINDOW after the last maintenance: {'base', 'now', 'percent'},
    or None while there are fewer than 2 * WINDOW such races."""
    medians = [r['median'] for r in since_maintenance(records)
               if r.get('drive') == drive and r.get('median')]
    if len(medians) < 2 * WINDOW:
        return None
    base = statistics.median(medians[:WINDOW])
    now = statistics.median(medians[-WINDOW:])
    return {'base': base, 'now': now, 'percent': 100 * (now - base) / base}


CREDIT_CAP = int(os.environ.get('CREDIT_CAP', '10000000000'))  # the most credits GT7 holds (1.11): more is lost


def cap(records, now, credit_cap=CREDIT_CAP, hours=2):
    """How far the last balance read is from the credit cap: {'balance', 'left', 'per_hour',
    'hours'}, with the rate from the balances of the races in the last `hours` hours
    (per_hour and hours None with fewer than two of them), or None with no balance."""
    kept = []
    for r in records:
        try:
            if r.get('balance'):
                kept.append((datetime.datetime.fromisoformat(r['time']).timestamp(), r['balance']))
        except (KeyError, TypeError, ValueError):
            pass
    if not kept:
        return None
    balance = kept[-1][1]
    recent = [k for k in kept if k[0] >= now - hours * 3600]
    per_hour = None
    if len(recent) >= 2 and recent[-1][0] > recent[0][0] and recent[-1][1] > recent[0][1]:
        per_hour = (recent[-1][1] - recent[0][1]) / ((recent[-1][0] - recent[0][0]) / 3600)
    left = max(credit_cap - balance, 0)
    return {'balance': balance, 'left': left, 'per_hour': per_hour,
            'hours': left / per_hour if per_hour else None}
