#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib"]
# ///

# Analyse a telemetry recording made with TELEMETRY_RECORD
# Usage: uv run gt7-analyze.py <file.gt7tel> [output-dir]
#        uv run gt7-analyze.py track <file.gt7tel> [lap]
#
# Prints a table per race and lap, and saves charts in output-dir (default
# <file>-analysis): the line driven coloured by speed, the speed over the lap
# distance, and the steering angle with the speed over 20 seconds. With a
# track line (below), it also shows how far each lap ran from it (d, metres,
# + towards the outside wall).
# track saves the line of one lap (default: the fastest of laps 2 on of the
# first race) as the track line for DRIVE=line (gt7/driver.py).

import json
import math
import os
import struct
import sys

from gt7 import driver, telemetry


def read(path):
    with open(path, 'rb') as f:
        if f.read(len(telemetry.RECORD_MAGIC)) != telemetry.RECORD_MAGIC:
            sys.exit('%s is not a telemetry recording' % path)
        while True:
            head = f.read(10)
            if len(head) < 10:
                return
            when, size = struct.unpack('<dH', head)
            packet = f.read(size)
            if len(packet) < size:
                return
            yield when, packet


def split_races(samples):
    """Runs of samples from lap 1 to the finish; a new race starts when the lap goes back."""
    races = []
    for s in samples:
        if s['laps'] <= 0 or s['lap'] < 1:
            continue
        if not races or s['lap'] < races[-1][-1]['lap']:
            races.append([])
        races[-1].append(s)
    return races


def lap_times(race):
    times, last = {}, None
    for s in race:
        if s['last'] > 0 and s['last'] != last and last is not None:
            times[s['lap'] - 1] = s['last']
        last = s['last']
    return times


def fmt(ms):
    return '%d:%06.3f' % (ms // 60000, ms % 60000 / 1000) if ms else '-'


def lap_stats(samples, track=None):
    speeds = [s['speed'] for s in samples]
    steer = [abs(math.degrees(s['steer'])) for s in samples if s['steer'] is not None]
    d = []
    if track:
        line = driver.LineDriver(track)
        d = [(line.update(s), line.d)[1] for s in samples]
    return {
        'max': max(speeds), 'mean': sum(speeds) / len(speeds), 'min': min(speeds),
        'steer': sum(steer) / len(steer) if steer else None,
        'steering': 100 * sum(1 for a in steer if a > 1) / len(steer) if steer else None,
        'd': (sum(d) / len(d), min(d), max(d)) if d else None,
    }


def distance(samples):
    out, total = [], 0.0
    for a, b in zip([samples[0]] + samples, samples):
        total += math.dist(a['position'], b['position'])
        out.append(total)
    return out


def charts(race, n, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    driven = [s for s in race if s['lap'] <= s['laps'] and s['on_track'] and not s['paused']]
    laps = sorted({s['lap'] for s in driven})
    fig, ax = plt.subplots(figsize=(8, 8))
    points = ax.scatter([s['position'][0] for s in driven], [s['position'][2] for s in driven],
                        c=[s['speed'] for s in driven], s=1, cmap='viridis')
    fig.colorbar(points, label='km/h')
    ax.set_aspect('equal')
    ax.set_title('Race %d: line driven' % n)
    fig.savefig(os.path.join(out, 'race%d-track.png' % n), dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5))
    for lap in laps:
        samples = [s for s in driven if s['lap'] == lap]
        ax.plot(distance(samples), [s['speed'] for s in samples], lw=0.8, label='lap %d' % lap)
    ax.set_xlabel('distance in the lap (m)')
    ax.set_ylabel('km/h')
    ax.set_title('Race %d: speed' % n)
    ax.legend(ncol=5, fontsize=8)
    fig.savefig(os.path.join(out, 'race%d-speed.png' % n), dpi=110)
    plt.close(fig)

    lap = laps[min(2, len(laps) - 1)]
    samples = [s for s in driven if s['lap'] == lap]
    t0 = samples[0]['time']
    window = [s for s in samples if s['time'] - t0 <= 20 and s['steer'] is not None]
    if window:
        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot([s['time'] - t0 for s in window], [math.degrees(s['steer']) for s in window], lw=0.8)
        ax.set_xlabel('seconds into lap %d' % lap)
        ax.set_ylabel('steering angle (deg)')
        speed = ax.twinx()
        speed.plot([s['time'] - t0 for s in window], [s['speed'] for s in window], color='tab:orange', lw=0.8)
        speed.set_ylabel('km/h', color='tab:orange')
        ax.set_title('Race %d: steering' % n)
        fig.savefig(os.path.join(out, 'race%d-steer.png' % n), dpi=110)
        plt.close(fig)


def samples_of(path):
    samples, sizes = [], {}
    counter = telemetry.Counter()
    for when, packet in read(path):
        s = telemetry.parse(packet)
        s['time'] = when
        samples.append(s)
        counter.add(s['packet_id'])
        sizes[len(packet)] = sizes.get(len(packet), 0) + 1
    return samples, sizes, counter


def make_track(path, lap=None):
    race = split_races(samples_of(path)[0])[0]
    driven = [s for s in race if s['lap'] <= s['laps'] and s['on_track'] and not s['paused']]
    if lap is None:
        times = lap_times(race)
        lap = min((t, n) for n, t in times.items() if n >= 2)[1]
    data = driver.build([s for s in driven if s['lap'] == lap])
    os.makedirs(os.path.dirname(driver.TRACK), exist_ok=True)
    with open(driver.TRACK, 'w') as f:
        json.dump(data, f)
    print('Saved the line of lap %d (%d points, %.0f m) to %s' % (
        lap, len(data['points']), len(data['points']) * driver.SPACING, driver.TRACK))


def main():
    if len(sys.argv) < 2:
        sys.exit('Usage: uv run gt7-analyze.py <file.gt7tel> [output-dir] | track <file.gt7tel> [lap]')
    if sys.argv[1] == 'track':
        make_track(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None)
        return
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(path)[0] + '-analysis'
    os.makedirs(out, exist_ok=True)
    track = driver.Track.load() if os.path.exists(driver.TRACK) else None
    samples, sizes, counter = samples_of(path)
    total = counter.packets + counter.missing
    print('%s: %d packets %s, %d missing (%.2f%%)' % (
        path, counter.packets, sizes, counter.missing, 100 * counter.missing / total if total else 0))
    for n, race in enumerate(split_races(samples), 1):
        times = lap_times(race)
        laps = race[0]['laps']
        finished = race[-1]['lap'] > laps
        print('\nRace %d: %s, %d laps%s, best %s' % (
            n, __import__('datetime').datetime.fromtimestamp(race[0]['time']).strftime('%Y-%m-%d %H:%M:%S'),
            laps, '' if finished else ' (not finished)', fmt(race[-1]['best'])))
        print('lap  time       min/mean/max km/h  steer deg  steering %%%s' % ('  d mean (min..max) m' if track else ''))
        driven = [s for s in race if s['lap'] <= laps and s['on_track'] and not s['paused']]
        for lap in sorted({s['lap'] for s in driven}):
            st = lap_stats([s for s in driven if s['lap'] == lap], track)
            print('%3d  %-9s  %4.0f/%5.1f/%4.0f    %9s  %10s%s' % (
                lap, fmt(times.get(lap)), st['min'], st['mean'], st['max'],
                '-' if st['steer'] is None else '%.2f' % st['steer'],
                '-' if st['steering'] is None else '%.0f' % st['steering'],
                '  %6.2f (%5.2f..%5.2f)' % st['d'] if st['d'] else ''))
        charts(race, n, out)
    print('\nCharts in %s' % out)


main()
