#!/usr/bin/env python3

# Receive Gran Turismo 7 telemetry and keep the latest state in a file
# Usage: gt7-telemetry.py <playstation-ip> <state-file>
#
# The state file holds one line, updated ~5 times a second:
#   epoch on_track paused loading lap laps speed_kmh position best_lap_ms last_lap_ms
# GT7 only sends to a host that keeps sending it heartbeats, and the packets
# are Salsa20 encrypted. The host firewall must allow UDP port 33740 in.

import os
import socket
import struct
import sys
import time

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


def state_line(p):
    flags = struct.unpack_from('<H', p, 0x8E)[0]
    lap, laps = struct.unpack_from('<hh', p, 0x74)
    best, last = struct.unpack_from('<ii', p, 0x78)
    position = struct.unpack_from('<h', p, 0x84)[0]
    speed = struct.unpack_from('<f', p, 0x4C)[0] * 3.6
    return '%d %d %d %d %d %d %d %d %d %d\n' % (
        time.time(), flags & 1, flags >> 1 & 1, flags >> 2 & 1,
        lap, laps, speed, position, best, last)


def main():
    host, path = sys.argv[1], sys.argv[2]
    parent = os.getppid()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', RECEIVE_PORT))
    sock.settimeout(1)
    last_heartbeat = last_write = 0
    while os.getppid() == parent:
        now = time.time()
        if now - last_heartbeat > 5:
            sock.sendto(b'A', (host, SEND_PORT))
            last_heartbeat = now
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        if now - last_write < 0.2:
            continue
        packet = decrypt(data)
        if packet is None:
            continue
        with open(path + '.tmp', 'w') as f:
            f.write(state_line(packet))
        os.replace(path + '.tmp', path)
        last_write = now


main()
