# Receive Gran Turismo 7 telemetry, keep the latest state in a file and
# optionally record every packet
#
# GT7 only sends to a host that keeps sending it heartbeats, and the packets
# are Salsa20 encrypted. The host firewall must allow UDP port 33740 in.
# Heartbeat 'A' gets the original 296-byte packet; 'B' (GT7 1.42 and later)
# adds the steering angle and the car's sway, heave and surge (316 bytes).

import datetime
import os
import signal
import socket
import struct
import sys
import time

KEY = b'Simulator Interface Packet GT7 ver 0.0'[:32]
SEND_PORT = int(os.environ.get('TELEMETRY_SEND_PORT', '33739'))
RECEIVE_PORT = int(os.environ.get('TELEMETRY_RECEIVE_PORT', '33740'))
NONCE_XOR = {b'A': 0xDEADBEAF, b'B': 0xDEADBEEF, b'~': 0x55FABB4F}  # per heartbeat type
MAGIC = 0x47375330
SIZE_B = 0x13C
HEARTBEAT_INTERVAL = 2  # seconds; GT7 stops sending some time after the last one
RECORD_MAGIC = b'GT7TEL1\n'  # then per packet: <d receive time> <H length> <decrypted packet>


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


def crypt(data, kind):
    """Salsa20 both ways: decrypt a packet, or encrypt one (for tests)."""
    iv1 = int.from_bytes(data[0x40:0x44], 'little')
    nonce = (iv1 ^ NONCE_XOR[kind]).to_bytes(4, 'little') + iv1.to_bytes(4, 'little')
    stream = b''.join(salsa20_block(KEY, nonce, i) for i in range((len(data) + 63) // 64))
    out = int.from_bytes(data, 'little') ^ int.from_bytes(stream[:len(data)], 'little')
    out = bytearray(out.to_bytes(len(data), 'little'))
    out[0x40:0x44] = data[0x40:0x44]  # the IV is sent in the clear
    return bytes(out)


def decrypt(data, kind=b'B'):
    """Return the decrypted packet, trying the given heartbeat type first, or None."""
    for k in [kind] + [k for k in NONCE_XOR if k != kind]:
        packet = crypt(data, k)
        if len(packet) >= 0x94 and struct.unpack_from('<I', packet, 0)[0] == MAGIC:
            return packet
    return None


def parse(p):
    """The fields this project uses, from a decrypted packet."""
    flags = struct.unpack_from('<H', p, 0x8E)[0]
    t = {
        'position': struct.unpack_from('<3f', p, 0x04),  # x, y (up), z in metres
        'velocity': struct.unpack_from('<3f', p, 0x10),  # m/s
        'rotation': struct.unpack_from('<3f', p, 0x1C),
        'angular_velocity': struct.unpack_from('<3f', p, 0x2C),
        'rpm': struct.unpack_from('<f', p, 0x3C)[0],
        'speed': struct.unpack_from('<f', p, 0x4C)[0] * 3.6,  # km/h
        'packet_id': struct.unpack_from('<i', p, 0x70)[0],
        'lap': struct.unpack_from('<h', p, 0x74)[0],
        'laps': struct.unpack_from('<h', p, 0x76)[0],
        'best': struct.unpack_from('<i', p, 0x78)[0],  # ms
        'last': struct.unpack_from('<i', p, 0x7C)[0],  # ms
        'race_position': struct.unpack_from('<h', p, 0x84)[0],
        'on_track': flags & 1, 'paused': flags >> 1 & 1, 'loading': flags >> 2 & 1,
        'gear': p[0x90] & 0x0f, 'throttle': p[0x91], 'brake': p[0x92],
        'steer': None, 'sway': None, 'heave': None, 'surge': None,
    }
    if len(p) >= SIZE_B:
        t['steer'] = struct.unpack_from('<f', p, 0x128)[0]  # radians
        t['sway'], t['heave'], t['surge'] = struct.unpack_from('<3f', p, 0x130)
    return t


def state_line(t, now):
    # epoch on_track paused loading lap laps speed_kmh position best_lap_ms last_lap_ms
    # gear throttle brake rpm steer_mrad   (throttle and brake 0-255; steer 0 without packet B)
    return '%d %d %d %d %d %d %d %d %d %d %d %d %d %d %d\n' % (
        now, t['on_track'], t['paused'], t['loading'], t['lap'], t['laps'], t['speed'],
        t['race_position'], t['best'], t['last'], t['gear'], t['throttle'], t['brake'],
        t['rpm'], (t['steer'] or 0) * 1000)


def log(text):
    print(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S ') + text, flush=True)


class Counter:
    """Packets received and missing (gaps in the packet ids) since the last report."""

    def __init__(self):
        self.packets = self.missing = 0
        self.last_id = None

    def add(self, packet_id):
        if self.last_id is not None and 0 < packet_id - self.last_id < 1000:
            self.missing += packet_id - self.last_id - 1
        self.last_id = packet_id
        self.packets += 1

    def report(self, kind):
        total = self.packets + self.missing
        log('  Telemetry: %d packets (%s), %d missing (%.2f%%)' % (
            self.packets, kind.decode(), self.missing, 100 * self.missing / total if total else 0))
        self.packets = self.missing = 0


class Receiver:
    """Receive GT7 telemetry until keep_going() turns false: keep the latest
    fields in .latest, write the state file, record every packet and log the
    packets received and missing at each finish. on_packet(fields) is called
    for every packet (~60 a second)."""

    def __init__(self, host, state_path=None, record_dir='', on_packet=None):
        self.host, self.state_path, self.record_dir = host, state_path, record_dir
        self.on_packet = on_packet
        self.latest = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', RECEIVE_PORT))
        self.sock.settimeout(0.5)

    def fresh(self, seconds=2):
        """The latest fields if they are at most this old, else None."""
        t = self.latest
        return t if t and time.time() - t['time'] <= seconds else None

    def run(self, keep_going):
        kind = b'B'
        b_works = False
        heartbeats = 0
        last_heartbeat = last_write = 0
        finished = False
        counter = Counter()
        record = None
        try:
            while keep_going():
                now = time.time()
                if now - last_heartbeat > HEARTBEAT_INTERVAL:
                    # until a 'B' packet arrives, alternate with 'A' for a GT7 without it
                    heartbeats += 1
                    sent = b'B' if b_works or heartbeats % 2 else b'A'
                    self.sock.sendto(sent, (self.host, SEND_PORT))
                    last_heartbeat = now
                try:
                    data = self.sock.recv(4096)
                except socket.timeout:
                    continue
                packet = decrypt(data, kind)
                if packet is None:
                    continue
                kind = b'B' if len(packet) >= SIZE_B else b'A'
                b_works = b_works or kind == b'B'
                t = parse(packet)
                t['time'] = now
                if self.latest is None:
                    text = '  Telemetry: packet %s (%d bytes)' % (kind.decode(), len(packet))
                    if self.record_dir:
                        name = os.path.join(self.record_dir, time.strftime('%Y%m%d-%H%M%S') + '.gt7tel')
                        try:
                            os.makedirs(self.record_dir, exist_ok=True)
                            record = open(name, 'ab')
                            record.write(RECORD_MAGIC)
                            text += ', recording to ' + name
                        except OSError as e:
                            text += ', WARNING: cannot record (%s)' % e
                    log(text)
                self.latest = t
                counter.add(t['packet_id'])
                if record:
                    record.write(struct.pack('<dH', now, len(packet)) + packet)
                if self.on_packet:
                    self.on_packet(t)
                if t['laps'] > 0 and t['lap'] > t['laps']:
                    if not finished:
                        counter.report(kind)
                    finished = True
                else:
                    finished = False
                if self.state_path and now - last_write >= 0.2:
                    with open(self.state_path + '.tmp', 'w') as f:
                        f.write(state_line(t, now))
                    os.replace(self.state_path + '.tmp', self.state_path)
                    last_write = now
                    if record:
                        record.flush()
        finally:
            if record:
                record.close()
            self.sock.close()


def main():
    # Usage: gt7-telemetry.py <playstation-ip> <state-file>; TELEMETRY_RECORD=<dir> records too
    host, path = sys.argv[1], sys.argv[2]
    signal.signal(signal.SIGTERM, lambda *args: sys.exit(0))  # close the recording on kill
    parent = os.getppid()
    Receiver(host, path, os.environ.get('TELEMETRY_RECORD', '')).run(lambda: os.getppid() == parent)
