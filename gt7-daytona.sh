#!/bin/bash

# Gran Turismo 7 Daytona Autopilot Script

# This work © 2025 by Jason Lonsberry is licensed under CC BY-NC-SA 4.0.
# To view a copy of this license, visit https://creativecommons.org/licenses/by-nc-sa/4.0/

set -e
trap exit_gracefully SIGINT

# To prevent sleep, launch with systemd-inhibit

# ---------- config ----------

KEYPRESS_LENGTH=0.08
LAP_MILES=2.6
LAPS=10
QUICKPRESS_LENGTH=0.01
RACE_PRIZE=9705000 # 1st place with clean race bonus
RACE_TIME=800 # seconds from race start to crossing the finish line
STRAIGHT_TIME=15 # seconds to drive straight after the start to avoid hitting cars ahead
WINDOW_NAME='Chiaki | Stream'

# ---------- key config ----------
# Key config MUST be set to match your Chiaki key config

ANALOG_L__R='bracketright' # default ']' Left analog pressing right
DPAD_R='Right'             # default 'Right'
KEY_R2='4'                 # default '4'
KEY_X='Return'             # default 'Return'

# ---------- dependencies ----------

if ! dpkg -s wmctrl >/dev/null 2>&1; then
  sudo apt install wmctrl
fi
if ! dpkg -s xdotool >/dev/null 2>&1; then
  sudo apt install xdotool
fi

# ---------- functions ----------

add() {
  echo "scale=1; $1 + $2" | bc
}

multiply() {
  echo "$1 * $2" | bc
}

hold() {
  xdotool search --name "$WINDOW_NAME" keydown "$1"
}

release() {
  xdotool search --name "$WINDOW_NAME" keyup "$1"
}

press() {
  xdotool search --name "$WINDOW_NAME" keydown "$1"
  sleep $KEYPRESS_LENGTH
  xdotool search --name "$WINDOW_NAME" keyup "$1"
}

quick_press() {
  xdotool search --name "$WINDOW_NAME" keydown "$1"
  sleep $QUICKPRESS_LENGTH
  xdotool search --name "$WINDOW_NAME" keyup "$1"
}

exit_gracefully() {
  printf '\nQuitting \n'
  release $ANALOG_L__R
  release $DPAD_R
  release $KEY_R2
  release $KEY_X
  exit
}

# ---------- main  ----------

RACE_MILES=$(multiply $LAP_MILES $LAPS)

current_miles=0.0
current_money=0
race_count=0

if ! wmctrl -l|grep "$WINDOW_NAME" >/dev/null 2>&1; then
  echo 'The Chiaki stream window was not found. Quitting'
  exit
fi

while true
do
  race_count=$(($race_count + 1))

  echo "Race $race_count"
  press $KEY_X
  sleep 2 # let GT7 register X before R2 goes down, or the race may not start
  hold $KEY_R2 # hold only after starting; GT7 menus ignore X while R2 is held
  sleep 6

  echo '  Race start'
  # time by wall clock: each xdotool call adds overhead, so counting ticks drifts
  steer_start=$((SECONDS + STRAIGHT_TIME))
  race_end=$((SECONDS + RACE_TIME))
  while [ $SECONDS -lt $race_end ]; do
    if [ $SECONDS -ge $steer_start ]; then
      quick_press $ANALOG_L__R
    fi
    sleep 0.5
  done

  echo '  Race ending'
  sleep 30
  release $KEY_R2

  echo 'Standings'
  sleep 20 # extra wait here to buffer for slow finishes
  press $KEY_X

  echo 'Rewards'
  press $KEY_X
  sleep 3

  current_miles=$(add $current_miles $RACE_MILES)
  current_money=$((current_money + RACE_PRIZE))

  printf "  Credits: %'d\n" $current_money
  press $KEY_X
  sleep 2

  echo "  Miles: $current_miles"
  press $KEY_X
  sleep 4

  echo 'Replay'
  press $KEY_X
  sleep 4
  press $KEY_X
  sleep 2
  press $KEY_X
  press $KEY_X
  sleep 5

  echo 'Retry'
  press $DPAD_R
  sleep 1
  press $KEY_X
  sleep 4
done
