#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["matplotlib"]
# ///

# Analyse a telemetry recording made with TELEMETRY_RECORD
# Usage: uv run gt7-analyze.py <file.gt7tel> [output-dir]
#
# Prints a table per race and lap, and saves charts in output-dir (default
# <file>-analysis): the line driven coloured by speed, the speed over the lap
# distance, and the steering angle with the speed over 20 seconds.
# "Scrape" is the share of the lap at full throttle while losing speed, a
# rough sign of rubbing the wall.

import math
import os
import struct
import sys

from gt7 import telemetry


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


def lap_stats(samples):
    speeds = [s['speed'] for s in samples]
    steer = [abs(math.degrees(s['steer'])) for s in samples if s['steer'] is not None]
    scrape = 0
    for a, b in zip(samples, samples[6:]):  # ~0.1 s apart
        if a['throttle'] >= 250 and b['time'] > a['time'] and \
                (b['speed'] - a['speed']) / (b['time'] - a['time']) < -3:
            scrape += 1
    return {
        'max': max(speeds), 'mean': sum(speeds) / len(speeds),
        'steer': sum(steer) / len(steer) if steer else None,
        'steering': 100 * sum(1 for a in steer if a > 1) / len(steer) if steer else None,
        'scrape': 100 * scrape / max(1, len(samples) - 6),
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


def main():
    if len(sys.argv) < 2:
        sys.exit('Usage: uv run gt7-analyze.py <file.gt7tel> [output-dir]')
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(path)[0] + '-analysis'
    os.makedirs(out, exist_ok=True)
    samples, sizes = [], {}
    counter = telemetry.Counter()
    for when, packet in read(path):
        s = telemetry.parse(packet)
        s['time'] = when
        samples.append(s)
        counter.add(s['packet_id'])
        sizes[len(packet)] = sizes.get(len(packet), 0) + 1
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
        print('lap  time       max km/h  mean km/h  steer deg  steering %  scrape %')
        driven = [s for s in race if s['lap'] <= laps and s['on_track'] and not s['paused']]
        for lap in sorted({s['lap'] for s in driven}):
            st = lap_stats([s for s in driven if s['lap'] == lap])
            print('%3d  %-9s  %8.0f  %9.1f  %9s  %10s  %8.1f' % (
                lap, fmt(times.get(lap)), st['max'], st['mean'],
                '-' if st['steer'] is None else '%.2f' % st['steer'],
                '-' if st['steering'] is None else '%.0f' % st['steering'], st['scrape']))
        charts(race, n, out)
    print('\nCharts in %s' % out)


main()
