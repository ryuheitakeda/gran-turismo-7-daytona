import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import gt7_daytona as g


class ConfigTest(unittest.TestCase):
    def test_parse(self):
        with tempfile.NamedTemporaryFile('w', suffix='.conf', delete=False) as f:
            f.write("# c\nDISPLAY=:20\nexport RACE_TIME=805 # note\nWINDOW_NAME='^A \\| B$'\nbad line\n")
        v = g.parse_config(f.name)
        os.unlink(f.name)
        self.assertEqual(v, {'DISPLAY': ':20', 'RACE_TIME': '805', 'WINDOW_NAME': '^A \\| B$'})

    def test_env_wins(self):
        os.environ['RACE_TIME'] = '123'
        try:
            self.assertEqual(g.Config(g.load_config('/nonexistent')).RACE_TIME, 123)
        finally:
            del os.environ['RACE_TIME']


class KeysTest(unittest.TestCase):
    def test_default_keys_have_scancodes(self):
        for k in ('bracketright', 'Right', '4', 'Return'):
            self.assertIn(k, g.SCAN_CODES)
        self.assertEqual(g.SCAN_CODES['4'], (0x05, False))
        self.assertEqual(g.SCAN_CODES['Right'], (0x4D, True))


class TelemetryTest(unittest.TestCase):
    def test_roundtrip(self):
        plain = bytearray(0x128)
        struct.pack_into('<I', plain, 0, 0x47375330)
        struct.pack_into('<f', plain, 0x4C, 100.0)
        struct.pack_into('<hh', plain, 0x74, 3, 10)
        struct.pack_into('<ii', plain, 0x78, 76856, 77000)
        struct.pack_into('<h', plain, 0x84, 1)
        struct.pack_into('<H', plain, 0x8E, 1)
        iv1 = 0x12345678
        nonce = (iv1 ^ 0xDEADBEAF).to_bytes(4, 'little') + iv1.to_bytes(4, 'little')
        stream = b''.join(g.salsa20_block(g.KEY, nonce, i) for i in range((len(plain) + 63) // 64))
        enc = bytearray(a ^ b for a, b in zip(plain, stream))
        enc[0x40:0x44] = iv1.to_bytes(4, 'little')  # the IV travels in the clear
        s = g.parse_state(g.decrypt(bytes(enc)))
        self.assertEqual((s.lap, s.laps, s.position, s.best, s.on_track, s.speed), (3, 10, 1, 76856, 1, 360))
        self.assertEqual(g.lap_time(76856), '1:16.856')


if __name__ == '__main__':
    unittest.main()
