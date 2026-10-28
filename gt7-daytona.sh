#!/bin/bash

# Gran Turismo 7 Daytona Autopilot Script

# This work © 2025 by Jason Lonsberry is licensed under CC BY-NC-SA 4.0.
# To view a copy of this license, visit https://creativecommons.org/licenses/by-nc-sa/4.0/

# Usage: gt7-daytona.sh [start|stop|stop-after-race|cancel-stop|status|log [lines]]
#   no argument  run in the foreground, quit with CTRL+C
#   start        run in the background, writing to $LOG_FILE
#   stop-after-race  stop at the start screen once the current race is over

set -e

# To prevent sleep, launch with systemd-inhibit

# ---------- config ----------
# Every value below can be set in $CONFIG_FILE (bash syntax) or overridden by an
# environment variable of the same name: environment > config file > default

CONFIG_FILE=${CONFIG_FILE:-$HOME/.config/gt7-daytona.conf}
if [ -f "$CONFIG_FILE" ]; then
  env_vars=$(export -p)
  . "$CONFIG_FILE"
  eval "$env_vars" || true # values from the environment win over the config file
fi

KEYPRESS_LENGTH=${KEYPRESS_LENGTH:-0.08}
LAP_MILES=${LAP_MILES:-2.6}
LAPS=${LAPS:-10}
LOCK_FILE=${LOCK_FILE:-${XDG_CACHE_HOME:-$HOME/.cache}/gt7-daytona.lock}
LOG_FILE=${LOG_FILE:-$HOME/gt7-daytona.log}
STOP_FILE=${STOP_FILE:-${XDG_CACHE_HOME:-$HOME/.cache}/gt7-daytona.stop-after-race}
MAINTENANCE_RACES=${MAINTENANCE_RACES:-20} # remind to check the engine every N races, 0 to turn off
PLAYSTATION_IP=${PLAYSTATION_IP:-} # set to read GT7 telemetry: detect the start, the finish and a stuck car
QUICKPRESS_LENGTH=${QUICKPRESS_LENGTH:-0.01}
FINISH_WAIT=${FINISH_WAIT:-8} # with telemetry, seconds from the finish line to the first X
RACE_PRIZE=${RACE_PRIZE:-9705000} # 1st place with clean race bonus
RACE_TIME=${RACE_TIME:-800} # seconds from "Race start" to crossing the finish line, used without telemetry
START_TIMEOUT=${START_TIMEOUT:-15} # with telemetry, quit if the car isn't on track this many seconds after X
STUCK_SPEED=${STUCK_SPEED:-30} # with telemetry, km/h below which the car counts as stuck
STUCK_TIME=${STUCK_TIME:-5} # with telemetry, quit after being stuck this many seconds
STRAIGHT_TIME=${STRAIGHT_TIME:-15} # seconds to drive straight after the start to avoid hitting cars ahead
WINDOW_NAME=${WINDOW_NAME:-'^Chiaki \| Stream$'} # xdotool regex, case-insensitive

# ---------- key config ----------
# Key config MUST be set to match your Chiaki key config

ANALOG_L__R=${ANALOG_L__R:-bracketright} # default ']' Left analog pressing right
DPAD_R=${DPAD_R:-Right}                  # default 'Right'
KEY_R2=${KEY_R2:-4}                      # default '4'
KEY_X=${KEY_X:-Return}                   # default 'Return'

# ---------- functions ----------

log() {
  echo "$(date '+%F %T') $*"
}

pause() { # sleep that a signal can interrupt at once
  sleep "$1" 9>&- & # don't pass on the lock
  wait $!
}

running_pid() { # print the pid of the running script, if any
  [ -f "$LOCK_FILE" ] || return 1
  if flock -n "$LOCK_FILE" true; then
    return 1
  fi
  cat "$LOCK_FILE"
}

send() { # send <keydown|keyup> <key>
  # look the window up on every key: the steering is tuned to the time this takes
  if ! xdotool search --name "$WINDOW_NAME" "$1" "$2" 2>/dev/null; then
    log 'ERROR: the Chiaki stream window is gone (stream disconnected?)'
    exit 1
  fi
}

hold() {
  send keydown "$1"
}

release() {
  send keyup "$1"
}

press() {
  send keydown "$1"
  sleep $KEYPRESS_LENGTH
  send keyup "$1"
}

quick_press() {
  send keydown "$1"
  sleep $QUICKPRESS_LENGTH
  send keyup "$1"
}

telemetry() { # read the latest telemetry into t_*; fails without fresh data
  [ -n "$PLAYSTATION_IP" ] && [ -f "$TELEMETRY_FILE" ] || return 1
  read -r t_time t_on_track t_paused t_loading t_lap t_laps t_speed t_position t_best t_last t_rest < "$TELEMETRY_FILE" || return 1
  [ $((EPOCHSECONDS - t_time)) -le 2 ]
}

lap_time() { # format milliseconds as m:ss.sss
  printf '%d:%06.3f' $(($1 / 60000)) "$(awk -v ms=$1 'BEGIN { printf "%.3f", (ms % 60000) / 1000 }')"
}

release_all() {
  for key in "$ANALOG_L__R" "$DPAD_R" "$KEY_R2" "$KEY_X"; do
    xdotool search --name "$WINDOW_NAME" keyup "$key" 2>/dev/null || true
  done
}

exit_gracefully() {
  release_all
  kill $(jobs -p) 2>/dev/null || true
  [ -z "$TELEMETRY_FILE" ] || rm -f "$TELEMETRY_FILE"
  log 'Quitting'
}

# ---------- commands ----------

case "$1" in
  '') ;;
  start)
    if pid=$(running_pid); then
      echo "Already running (pid $pid)"
      exit 1
    fi
    setsid -f "$0" >> "$LOG_FILE" 2>&1 < /dev/null
    sleep 2
    tail -n 5 "$LOG_FILE"
    exit
    ;;
  stop)
    if ! pid=$(running_pid); then
      echo 'Not running'
      exit
    fi
    kill -INT "$pid"
    for i in $(seq 50); do
      if ! running_pid >/dev/null; then
        echo 'Stopped'
        exit
      fi
      sleep 0.1
    done
    echo "Still running (pid $pid)"
    exit 1
    ;;
  status)
    if pid=$(running_pid); then
      echo "Running (pid $pid)"
    else
      echo 'Not running'
    fi
    tail -n 5 "$LOG_FILE" 2>/dev/null || true
    exit
    ;;
  stop-after-race)
    if ! pid=$(running_pid); then
      echo 'Not running'
      exit 1
    fi
    touch "$STOP_FILE"
    echo 'Will stop at the start screen after this race'
    exit
    ;;
  cancel-stop)
    rm -f "$STOP_FILE"
    echo 'Will keep racing'
    exit
    ;;
  log)
    tail -n "${2:-30}" "$LOG_FILE"
    exit
    ;;
  *)
    echo "Usage: $0 [start|stop|stop-after-race|cancel-stop|status|log [lines]]" >&2
    exit 2
    ;;
esac

# ---------- dependencies ----------

missing=''
for cmd in xdotool flock awk; do
  if ! command -v $cmd >/dev/null 2>&1; then
    missing="$missing $cmd"
  fi
done
if [ -n "$missing" ]; then
  echo "Missing commands:$missing. Install them first (e.g. sudo apt install xdotool)" >&2
  exit 1
fi

export DISPLAY
if [ -z "$DISPLAY" ]; then
  echo 'DISPLAY is not set. Run inside the desktop session or set DISPLAY (e.g. DISPLAY=:20)' >&2
  exit 1
fi
if ! xdotool getdisplaygeometry >/dev/null 2>&1; then
  echo "Cannot open display $DISPLAY. Quitting" >&2
  exit 1
fi

# ---------- main  ----------

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9<>"$LOCK_FILE"
if ! flock -n 9; then
  echo "gt7-daytona.sh is already running (pid $(cat "$LOCK_FILE")). Quitting" >&2
  exit 1
fi
echo $$ > "$LOCK_FILE"

WINDOW_ID=$(xdotool search --name "$WINDOW_NAME" 2>/dev/null | head -n 1)
if [ -z "$WINDOW_ID" ]; then
  echo "The Chiaki stream window was not found on $DISPLAY. Quitting" >&2
  exit 1
fi

TELEMETRY_FILE=""
trap exit_gracefully EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

log "Started: RACE_TIME=$RACE_TIME STRAIGHT_TIME=$STRAIGHT_TIME RACE_PRIZE=$RACE_PRIZE display=$DISPLAY window=$WINDOW_ID"

if [ -n "$PLAYSTATION_IP" ]; then
  TELEMETRY_FILE=${XDG_RUNTIME_DIR:-/tmp}/gt7-telemetry.state # read by gt7-web.py
  "$(dirname "$0")/gt7-telemetry.py" "$PLAYSTATION_IP" "$TELEMETRY_FILE" 9>&- &
  for i in $(seq 10); do
    pause 1
    if telemetry; then
      break
    fi
  done
  if telemetry; then
    log "Telemetry from $PLAYSTATION_IP"
  else
    log "WARNING: no telemetry from $PLAYSTATION_IP (is UDP port 33740 open?); timing the race with RACE_TIME"
  fi
fi

RACE_MILES=$(awk -v m="$LAP_MILES" -v n="$LAPS" 'BEGIN { printf "%.1f", m * n }')

current_miles=0.0
current_money=0
race_count=0

rm -f "$STOP_FILE"

while true
do
  if [ -f "$STOP_FILE" ]; then
    rm -f "$STOP_FILE"
    log 'Stopped after the race as requested; the game is at the start screen'
    exit 0
  fi
  race_count=$(($race_count + 1))

  log "Race $race_count"
  if [ $race_count -eq 1 ]; then
    # the start screen hides its menu after a while without input, and the
    # first X only brings it back; if the menu was showing, this X starts the
    # race and the next one lands on the loading screen
    press $KEY_X
    pause 2
  fi
  press $KEY_X
  pause 2
  hold $KEY_R2 # hold only during the race, never in the menus
  pause 6

  start_deadline=$((SECONDS + START_TIMEOUT - 8))
  while telemetry && [ "$t_on_track" -eq 0 ]; do
    if [ $SECONDS -ge $start_deadline ]; then
      log 'ERROR: the race did not start (telemetry: the car is not on track)'
      exit 1
    fi
    pause 0.5
  done

  if telemetry; then
    log '  Race start (telemetry: Race ending at the finish line)'
  else
    log "  Race start (Race ending at $(date -d "+$RACE_TIME seconds" +%T))"
  fi
  # time by wall clock: each xdotool call adds overhead, so counting ticks drifts
  steer_start=$((SECONDS + STRAIGHT_TIME))
  race_end=$((SECONDS + RACE_TIME))
  slow_since=''
  result=''
  while true; do
    if telemetry; then
      if [ "$t_laps" -gt 0 ] && [ "$t_lap" -gt "$t_laps" ]; then
        result=" (P$t_position, best lap $(lap_time $t_best))"
        break
      fi
      if [ "$t_paused" -eq 0 ] && [ "$t_speed" -lt "$STUCK_SPEED" ] &&
         { [ "$t_lap" -ge 1 ] || [ $SECONDS -ge $steer_start ]; }; then
        slow_since=${slow_since:-$SECONDS}
        if [ $((SECONDS - slow_since)) -ge "$STUCK_TIME" ]; then
          log "ERROR: the car is stuck (lap $t_lap, $t_speed km/h for ${STUCK_TIME}s)"
          exit 1
        fi
      else
        slow_since=''
      fi
      if [ $SECONDS -ge $((race_end + 120)) ]; then
        log "ERROR: no finish after $((RACE_TIME + 120))s (lap $t_lap of $t_laps)"
        exit 1
      fi
    elif [ $SECONDS -ge $race_end ]; then
      break
    fi
    if [ $SECONDS -ge $steer_start ]; then
      quick_press $ANALOG_L__R
    fi
    pause 0.5
  done

  log "  Race ending$result"
  if [ -n "$result" ]; then
    # telemetry saw the car cross the line, so no buffer for a late finish is needed
    release $KEY_R2
    pause $FINISH_WAIT
    log 'Standings'
  else
    pause 30
    release $KEY_R2

    log 'Standings'
    pause 20 # extra wait here to buffer for slow finishes
  fi
  press $KEY_X

  log 'Rewards'
  press $KEY_X
  pause 3

  current_miles=$(awk -v a="$current_miles" -v b="$RACE_MILES" 'BEGIN { printf "%.1f", a + b }')
  current_money=$((current_money + RACE_PRIZE))

  log "$(printf "  Credits: %'d" $current_money)"
  press $KEY_X
  pause 2

  log "  Miles: $current_miles"
  press $KEY_X
  pause 4

  log 'Replay'
  press $KEY_X
  pause 4
  press $KEY_X
  pause 2
  press $KEY_X
  press $KEY_X
  pause 5

  log 'Retry'
  press $DPAD_R
  pause 1
  press $KEY_X
  pause 4

  if [ "$MAINTENANCE_RACES" -gt 0 ] && [ $((race_count % MAINTENANCE_RACES)) -eq 0 ]; then
    log "  $race_count races done: check the oil and engine condition"
  fi
done
