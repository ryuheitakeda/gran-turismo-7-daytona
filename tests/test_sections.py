import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import gt7_sections as s

TABLE = """0'26.163-0.198
0'14.440-0.850
0'25.693-061790
1'06.296-06.639
.1'06.296
. 1'06.292
"""


class SectionsTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(s.parse_table(TABLE), ([25693, 14440, 26163], 66296))

    def test_rejects_misread_sum(self):
        self.assertIsNone(s.parse_table(TABLE.replace("0'26.163", "0'26.166")))

    def test_rejects_short_table(self):
        self.assertIsNone(s.parse_table("0'26.163-0.198\n0'14.440-0.850\n"))


if __name__ == '__main__':
    unittest.main()
