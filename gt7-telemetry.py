#!/usr/bin/env python3

# Receive Gran Turismo 7 telemetry and keep the latest state in a file
# Usage: gt7-telemetry.py <playstation-ip> <state-file>
#
# The state file holds one line, updated ~5 times a second:
#   epoch on_track paused loading lap laps speed_kmh position best_lap_ms last_lap_ms
#   gear throttle brake rpm steer_mrad   (throttle and brake 0-255)
# TELEMETRY_RECORD=<dir> also records every packet there (see gt7-analyze.py).
# The work is done in gt7/telemetry.py.

from gt7 import telemetry

telemetry.main()
