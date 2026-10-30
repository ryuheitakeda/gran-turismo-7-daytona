# Gran Turismo 7 Daytona Autopilot Script

## Summary

This script is the digital equivalent of using a rubber-band on your controller.  It will hold down the gas and steer slightly right during the race and will navigate the menu to restart in between races.

## Reasons For

- It's a clear text bash script.
- It uses only common, open-source linux tools: chiaki and xdotool (plus flock and awk, which every distribution ships).
- It can make your grind time more productive and more hands-off.
- With the setup below, a race takes ~14 minutes and pays 9,705,000 credits (1st place with the clean race bonus), making it easier to stop without losing progress.
- It is very stable.  It has been recorded to successfully loop over 50 times in a single run before the test was stopped.
- There is no need to adjust the AI racing difficulty.
- You might feel that using a sophisticated autonomous driving script is too close to cheating, but that using a digital rubber-band is okay.

## Reasons Against

- It requires a linux X11 desktop session, real or virtual (e.g. Chrome Remote Desktop), because xdotool only works with X11 windows.
- By design, it's very basic compared to other driving scripts; it can only handle oval tracks.
- It drives blind: it doesn't look at the screen, so it can't notice when a menu shows up that it doesn't expect.
- You can make more money using input-recorded driving scripts to complete higher-reward races.
- You might feel that even this much automation is a form of cheating.

## Preface

- The strategy defined below is taken from [RAKIN8R](https://www.reddit.com/user/RAKIN8R/)'s guide [Daytona AFK Grind Setup](https://www.reddit.com/r/GranTurismo7/comments/1817sqm/almost_15m_per_hour_daytona_afk_grind_setup/) on reddit.  Please refer to [this post](https://www.reddit.com/r/GranTurismo7/comments/1817sqm/almost_15m_per_hour_daytona_afk_grind_setup/) and [this post](https://www.reddit.com/r/GranTurismo7/comments/180kegp/new_daytona_afk_grind_setup/) for questions and clarifications.
  - He recommends an engine-swapped Honda Beat but the script can work for any car.
  - If reddit doesn't open for you, the same setup with screenshots is in his [GTPlanet post](https://www.gtplanet.net/forum/threads/how-i-still-make-over-2-300-000-credits-hour-through-custom-races-using-a-kangoo-1-63.424206/post-14142578).  The tune values are also copied below.
- To maximize rewards, create the race while using a low-PP tune and then switch to a high-PP tune once the race has been created.
  - Race rewards are determined by the difference between your PP and the opponents' PP but are not recalculated when you change car tunes inside the race-start menu.

## Setup

- Install Chiaki
  - Install from your favorite software manager or from the terminal with `sudo apt install chiaki`.  Avoid `sudo snap install chiaki`: the snap is an older third-party package (2.1.1, 2021; Ubuntu 24.04's apt has 2.2.0).
  - You **must pair Chiaki with your Playstation** before using the script.
  - Pairing is not hard per-se but it's a multi-step process that's worth using a guide for the first time.
  - Pairing asks for your PSN Account ID (base64).  [psn-account-id.py](https://github.com/streetpea/chiaki-ng/blob/main/scripts/psn-account-id.py) prints it after you log in to PSN in a browser.
- Install xdotool with `sudo apt install xdotool`.
- Download the script.  Give it execution permission if needed.
  - The script doesn't install anything itself; it tells you which commands are missing.
- Create a custom race at Daytona (make sure to save your settings)
  - Track: Daytona Tri-Oval
  - Race Type: Lap
  - Number of Laps: 10
  - Number of Cars: 20
  - Starting Grid: 20
  - Starting Type: Grid Start
    - With a rolling start (50 m interval) the car hit the car ahead at full throttle in 2 out of 3 races.
  - Mechanical Damage: None
  - Tire/Fuel: Off
  - Grip Reduction: Low
  - Weather:  Preset, S01, Midnight
  - Rivals: Select from garage
    - Set all opponents to the same VGT car, something with extremely high PP but cripple the VGT car's top speed beforehand with a transmission modification
    - The guide uses the SRT Tomahawk X VGT with a racing transmission.
  - Rivals Difficulty: Professional Level
  - Penalties:  All Off
  - Correct Vehicle Course After Wall Collision: Off
- Set up the Honda Beat as described in the guide above.  These are the values from his GTPlanet screenshots:
  - Engine swap: K20C1 (Civic '20).  Stock wheels and bumper, no wing, no roll cage (the widebody is optional).
  - Tyres: Comfort Hard front, Racing Soft rear
  - Suspension (fully customisable), front / rear: body height 180 / 180, anti-roll bar 10 / 10, damping compression 40 / 40, damping expansion 50 / 50, natural frequency 3.20 / 3.35, negative camber 6.0 / 0.0, toe 1.00 / 0.00
  - Differential (fully customisable), rear: initial torque 60, acceleration sensitivity 60, braking sensitivity 5; front all 0; torque distribution 0:100
  - Downforce 0 / 0, ECU Normal 100%, ballast 0, power restrictor 100%
  - Transmission: fully customisable racing, manual ratios 1.992 / 1.203 / 0.906 / 0.729 / 0.621, final 3.500
    - Because the script's steering creates friction with the wall, it needs a top speed of about 350 kph.  With these ratios 5th gear already tops out at ~352 kph.
  - Nitrous 21% (the script doesn't press the nitrous button)
  - Turbo High-RPM with strong anti-lag, racing intercooler, intake, silencer, exhaust manifold, clutch and flywheel; bore up, stroke up and polished ports; weight reduction stages 1-3; normal brakes and steering
  - If the car goes over 300 PP, add ballast at the front (position -50).
- Set the assists
  - Transmission: Automatic (required; the script never shifts gears)
  - Automatic braking assists: Off (recommended; the script expects full throttle the whole race)
  - Traction Control 5 and ASM On.  With lower traction control and ASM off, the car spun after touching the wall.
  - Steering and countersteer assists: Off (recommended)

## Configuration

- Every setting can be put in `~/.config/gt7-daytona.conf` (bash syntax) or given as an environment variable of the same name.  The environment wins over the file, and the file wins over the defaults.  For example:

  ```bash
  DISPLAY=:20
  RACE_TIME=805
  ```

- `PLAYSTATION_IP` (default empty): your Playstation's IP address.  When set, the script reads GT7's telemetry (see below) to check that the race started, to end the race at the finish line, and to quit when the car gets stuck.
- `START_TIMEOUT` (default 15), `STUCK_SPEED` (default 30) and `STUCK_TIME` (default 5): with telemetry, quit when the car isn't on track that many seconds after pressing X, or stays below `STUCK_SPEED` km/h for `STUCK_TIME` seconds during the race.  With `PILOT=1` a stuck car doesn't end the run: it logs it and drives on with R2 (on the grid it lets go of R2 and presses it again), because GT7 puts a car that's stuck back on the track.  Still stuck after `STUCK_RETRY` seconds (default 20), it pauses the race and picks Retry, which restarts it at the grid (see "Recovery"), and only quits when it is still stuck after `STUCK_GIVE_UP` seconds (default 60).
- `RACE_TIME` (default 800): seconds from the "Race start" log line until you cross the finish line.  It was measured with the grid start above; you will need to set it according to your vehicle speed.  With telemetry it is only used when the telemetry stops coming.
  - If you're not sure, start with the time it takes to rubber-band the race.
- `STRAIGHT_TIME` (default 15): seconds to drive straight after the start before steering towards the wall.
- `LAUNCH_THROTTLE` (default 1), `LAUNCH_TIME` (default 3), `LAUNCH_KPSI` (default 0) and `LAUNCH_MAX` (default 0.5): with `PILOT=1`, how the car moves off.  From standstill R2 is at `LAUNCH_THROTTLE`, kept for the first third of `LAUNCH_TIME` seconds after moving off and then raised to full by its end.  With `DRIVE=line`, until `STRAIGHT_TIME` the stick holds the heading along the track line, `LAUNCH_KPSI` stick per radian, at most `LAUNCH_MAX`; 0 leaves the stick alone.  The defaults are right with traction control 5.  With traction control 3 the laps are about 3.5 seconds quicker, but full R2 from the grid spun the rear out and put the car into the wall in 4 of 9 starts; `LAUNCH_THROTTLE=0.5 LAUNCH_KPSI=2` is meant for that and is untried.
- `RACE_PRIZE` (default 9705000): only used to total the credits in the log.  If you use a different car or setup, set it to the reward you get.
- `MAINTENANCE_RACES` (default 20): log a reminder to check the oil and engine every that many races; 0 turns it off.
- `RACES_FILE` (default `~/gt7-races.jsonl`) and `MAINT_LAP_PCT` (default 1.5): with `PILOT=1`, each race's lap times and top speed go to `RACES_FILE`, and the log says when the laps are `MAINT_LAP_PCT` percent slower than after the last maintenance; see "Engine wear".
- `TELEMETRY_RECORD` (default empty): with telemetry, a directory to record every packet in (about 70 MB an hour) for `gt7-analyze.py`; see "Recording and analysis".
- `SCREEN_RECORD` (default empty): a directory to keep screenshots of the Chiaki window in: one before each menu press, named after the step, one a second from the finish to the next start, and one every 30 seconds during the race.  It needs `xwd` (`sudo apt install x11-apps`).
- `QUICKPRESS_LENGTH` (default 0.01) and `KEYPRESS_LENGTH` (default 0.08): how long the steering taps and the menu presses last, in seconds.  For a steering tap the window is looked up again before the key is released, which adds about 0.04 seconds; the steering is tuned with that included.  Menu presses last exactly `KEYPRESS_LENGTH`: held longer, GT7 can move the cursor twice.
- `WINDOW_NAME` (default `^Chiaki \| Stream$`): the Chiaki stream window title as an xdotool regular expression (case-insensitive).
- `ANALOG_L__R`, `DPAD_L`, `DPAD_R`, `KEY_O`, `KEY_R2`, `KEY_X`: keys that MUST match your Chiaki key config.  The defaults are Chiaki's default keys.
- `TRAFFIC` (default log): with `PILOT=1`, read the course map at the top right of the race once a second and log a car within `TRAFFIC_WITHIN` metres ahead (default 200); `off` turns it off.  `TRAFFIC_ACTION=inside` holds the stick `TRAFFIC_STICK` (default -0.25, left) for a moment on the straights while a car is close ahead; it is an experiment, off by default.
- `NITRO` (default off): with `PILOT=1` and `DRIVE=line`, `straights` holds `NITRO_BUTTON` (default `l3`, GT7's nitrous button; the car needs the part) in `NITRO_ZONES`, metres along the track line (default `1600-2300,300-550,3450-3650`).  Those are where the car speeds up and traction control 5 leaves the power alone: in the bankings and the tri-oval it cuts the power almost all the time, so nitrous there would be wasted.  An experiment too.
- `DRIVE` (default pwm): with `PILOT=1`, how to steer: `pwm` (taps like the keys), `shadow` (taps, and log for each lap what `line` would do) or `line` (steer by the track line, see "Steering by the line"; with `WALL_GAP=0.1` the fastest found).  `WALL_GAP` (default 0.3), `STEER_KD` (0.1), `STEER_KPSI` (1.0), `STEER_MAX` (0.3) and `CURVE_STICK` (0) tune `line`.
- `MENUS` (default auto): how to get through the screens after the race: `screen` (look at the screen before each press, see "Screens"), `timer` (press on a timer), or `auto`: `screen` once the screens are learned.  The "Started:" log line says which.
- `LOG_FILE` (default `~/gt7-daytona.log`) and `LOCK_FILE` (default `~/.cache/gt7-daytona.lock`): used by the background commands below.

## Directions

- Start your Playstation and start Gran Turismo 7.
- Start Chiaki and connect to your Playstation.
- With your low PP tune selected, start a custom race at Daytona and load the custom race settings.
- Enter the race itself.  Switch to your high PP tune.
- With the arrow on the Start button, start the script.
  - The start screen hides its menu after a while without input, and the first X press only brings it back.  So before the first race the script presses X twice, 2 seconds apart; if the menu was showing, the second press lands on the loading screen.  With the screens learned (`MENUS=screen`), it looks at the screen before every race instead, and presses X once to wake it when the menu has hidden.
  - `./gt7-daytona.sh` runs it in the terminal.  When you're done, exit the script by pressing `CTRL+C`.
  - `./gt7-daytona.sh start` runs it in the background and writes the log to `~/gt7-daytona.log`.  Use `./gt7-daytona.sh status`, `./gt7-daytona.sh log` and `./gt7-daytona.sh stop` to check on it and stop it.
  - From an SSH session, set `DISPLAY` to the desktop that shows Chiaki (e.g. `DISPLAY=:20` in the config file).
- `./gt7-daytona.sh stop-after-race` lets the current race finish and stops at the start screen, ready for the next `start`; `./gt7-daytona.sh cancel-stop` takes it back.
- Only one copy of the script can run at a time.
- The script releases every key it holds when it quits, whether by `CTRL+C`, `stop`, `kill` or an error.  Only `kill -9` can leave R2 held down in Chiaki; release it with `xdotool search --name '^Chiaki \| Stream$' keyup 4`.
- If the Chiaki stream window disappears (e.g. the stream disconnects), the script logs an error and quits.

## Telemetry

- GT7 sends live telemetry (lap, speed, position, whether the car is on track) to a computer that sends it heartbeats over UDP.  `gt7-telemetry.py` receives it with nothing but python3; GT7 needs no setting for it.
- Let the telemetry through the computer's firewall, e.g. `sudo ufw allow from <playstation-ip> to any port 33740 proto udp`.
- Set `PLAYSTATION_IP` in the config file.  The log says "Telemetry from ..." at start, and "Race ending (P1, best lap 1:16.856)" when the car crosses the finish line.
- GT7 1.42 and later also send the steering angle when asked with heartbeat "B", which the script sends (`TELEMETRY_PACKET=A` for an older GT7).  GT7 keeps the format of a stream it is already sending, so after a program that asked for "A" the packets stay "A" until that stream has run out.  At each finish the log says how many packets came and how many were lost on the way, e.g. "Telemetry: 48210 packets (B), 3 missing (0.01%)".
- Without telemetry the script times the race with `RACE_TIME` as before.

## Recording and analysis

- To see where a race loses time, record it, e.g. `TELEMETRY_RECORD=~/gt7-data/telemetry SCREEN_RECORD=~/gt7-data/frames ./gt7-daytona.sh start`.  Nothing is recorded unless these are set.
- `./gt7-analyze.py <recording.gt7tel>` needs [uv](https://docs.astral.sh/uv/), which installs matplotlib for it.  For each lap it prints the lap time, the top and average speed, the steering, and "scrape": the share of the lap at full throttle while losing speed, a rough sign of rubbing the wall.  It saves charts next to the recording: the line driven coloured by speed, the speed over each lap, and the steering over 20 seconds.
- `./gt7-screen.py snap <file.png>` saves a screenshot of the Chiaki stream window, and `./gt7-screen.py record --every 1 <dir> <label>` keeps saving them.  They show the game only on a display Chiaki draws its video on; on Chrome Remote Desktop's virtual display they show Chiaki's host list.

## Screens

- With Chiaki on a display that shows its video, the script looks at the screen after the race instead of pressing on a timer.  It skips the "1st" scene after the finish line, goes through the results and the replay, and moves the cursor to Retry from wherever it is, pressing only when the screen it expects is showing.  That's about 45 seconds quicker per race, and a press that GT7 misses no longer leaves the menus out of step.
- Teach it the screens once, from screenshots of your own (e.g. a race with `SCREEN_RECORD` set): `./gt7-screen.py learn <screen> <file.png>` for each of `start` (the start screen, cursor on Start), `finish` ("1st" after the finish line), `standings`, `rewards`, `replay` (the replay without its menu), `replay-menu` (with it), `result` (the race result), `result-menu` (the Replay button's menu open on it) and `race`.  `./gt7-screen.py classify <dir>` shows what it makes of a folder of screenshots, and `./gt7-screen.py classify` of the window now.
- The references go to `~/.config/gt7-daytona/screens` (`SCREEN_REFERENCES`).  They are not in this repository, because they are pictures of the game.
- A screen is told by its titles, buttons and hints: their white pixels are compared with the reference, so the moving 3D background behind some of them doesn't count.  The button the cursor is on is told by its white edge.
- If the screens after the race don't lead back to the start screen within 150 seconds, the script logs an error and quits.

## Steering by the line

- The taps keep the car against the outside wall all the way round: the recordings show the same line every lap to within a few centimetres, with the steering pulled towards the wall 90% of the time.  That rubbing is where most of the speed goes.
- `./gt7-analyze.py track <recording.gt7tel> [lap]` saves the line of a lap (default the fastest from lap 2 on) as the track line, `~/.config/gt7-daytona/track.json` (`TRACK`).
- With `PILOT=1 DRIVE=line` the car's position is projected onto the line 60 times a second.  The left stick is set to keep the car `WALL_GAP` metres inside the line, heading along it: `-(STEER_KD × (d + WALL_GAP) + STEER_KPSI × heading)` within `±STEER_MAX`.  Here d is the distance towards the wall in metres and heading the angle towards it in radians.  More than 8 m off the line (after a collision, say), it taps for the rest of the race.
- With `CURVE_STICK` above 0 it also steers left where the line bends, by that much in the sharpest bend (30 m ahead).  Measured on 2026-10-29, that does nothing: GT7 ignores the stick up to about 0.136 (`STEER_PROBE=1` measures that once, on lap 3's back straight), and even at 0.3, the front wheels 13 degrees to the left, the car stayed on the wall and went through the banking at the same 150 km/h.  The corner speed is set by the car, not the steering.
- So the fastest way found is `DRIVE=line` with `WALL_GAP=0.1`: the stick stays inside the dead zone, the car rides the wall with no steering at all, and laps in 76.5 seconds against 79.2 with the taps (the taps' small right swings cost speed).  On the wall with no input the telemetry's steering angle reads 6 to 8 degrees left: the wall deflects the front wheels.
- `DRIVE=shadow` taps as usual and logs each lap's d, heading and stick, to check the line before steering by it.  The analysis table shows each lap's d against the line too.

## Recovery

- When the car is stuck (below `STUCK_SPEED` for `STUCK_TIME` seconds), the script drives on, since GT7 puts a car that's stuck back on the track; on the grid it lets go of R2 and presses it again.  If that hasn't helped after `STUCK_RETRY` seconds, it presses OPTIONS, moves to Retry on the pause menu and presses X: GT7 restarts the race at the grid, with no confirmation, and the script drives it as a new race.  The pause menu is told by its bar of four buttons, so it needs no reference of its own; the `race` reference must be learned.  With the car nose-first in the wall, lit stands behind POSITION and LAP can make the race unrecognisable; a screen it can't tell then counts as the race while the telemetry says the race runs unpaused.
- `touch ~/.cache/gt7-daytona.retry` makes it retry the race now (to try the recovery, or to give up a race that has gone wrong), and `touch ~/.cache/gt7-daytona.taps` makes it steer with taps for the rest of the session.
- When the screens after a race don't lead back to the start screen, or the race doesn't start, or the car stays stuck, the script keeps a screenshot (`SHOTS_DIR/error-<time>.png`) and quits; the web page shows the newest one while the script isn't running.
- Twice on 2026-10-29 the car hit a lapped car that was on the wall line and ended up stuck or spun.  The telemetry doesn't say where the other cars are, so the script reads the course map (`TRAFFIC`); for now it only logs them (`~/gt7-data/traffic.jsonl`), to work out how to pass them.

## Rewards

- With `PILOT=1`, `MENUS=screen` and tesseract (`sudo apt install tesseract-ocr`), the script reads the credits in the start screen's top bar before each race, and the balance on the rewards screen once it has filled in.  The difference is the reward.  The log says "Reward: 12,780,000 Cr (balance ...)", with a warning when it's less than `RACE_PRIZE` (the clean race bonus lost to a bump, say).  Each rewards screen is kept in `SHOTS_DIR` (default `~/gt7-data/shots`, the newest 50).
- The web page counts the credits from those rewards (`RACE_PRIZE` for races without one) and shows the newest rewards screen.

## Engine wear

- With `PILOT=1` the log has each lap's time and top speed, and `RACES_FILE` gets a line per race: its laps, the median of laps 2 on, the best lap, the top speed and the way it was steered.
- After an oil change or an engine overhaul, run `./gt7-daytona.sh maintenance-done` (or press the web page's button).  The first 5 races after it set the laps to compare with.  When the median lap of the last 5 races is `MAINT_LAP_PCT` percent slower than those, the log and the web page say it's time to see to the engine.  Races steered differently (taps or the track line) aren't compared with each other.
- The web page shows the median lap of each of the last 30 races.

## Virtual gamepad

- Keys can only push the stick all the way.  A virtual gamepad (Linux uinput) can send any stick and trigger value, and doesn't depend on which window has the focus.  Chiaki reads it like a real pad and adds it to the keys.  It looks like an Xbox 360 pad: A is cross, B circle, X square, Y triangle, START options.
- `/dev/uinput` must be writable for you; on this setup Sunshine's udev rule already does that.  For Chiaki to open the pad, install the rule once: `sudo install -m 644 70-gt7-pad.rules /etc/udev/rules.d/ && sudo udevadm control --reload`.
- `./gt7-pad.py check` makes the pad, checks that Chiaki opened it and removes it, without pressing anything.  `./gt7-pad.py press <button>` and `./gt7-pad.py hold <button>` press a button (cross, circle, square, triangle, l1, r1, share, options, l3, r3, up, down, left, right).  Only press buttons while the script is not racing.
- The pad disappears when its process ends, even with `kill -9`, so nothing stays pressed.

## Web page

- `./gt7-web.py start` serves a page on the computer's Tailscale address, port 8077 (`WEB_ADDRESS`, `WEB_PORT`); `stop` and `status` work as for the script.
- It shows the live telemetry, the races, wins and credits since the script started and for today, and the credits per hour.  Credits count races won (P1) at `RACE_PRIZE`, so they are an estimate.
- Its buttons start the script (put the cursor on Start first), stop it after the current race, or stop it at once.
- Let only Tailscale through the firewall, e.g. `sudo ufw allow in on tailscale0 to any port 8077 proto tcp`.

## Running without a monitor (Chrome Remote Desktop)

- Install a light desktop and Chrome Remote Desktop: `sudo apt install --no-install-recommends xfce4 xfce4-terminal dbus-x11` and the `.deb` from <https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb>.
- `echo 'exec /etc/X11/Xsession /usr/bin/xfce4-session' > ~/.chrome-remote-desktop-session`
- Register the host with the command from <https://remotedesktop.google.com/headless>.  Add `--pin=<6+ digits>` to it, because it can't ask for the PIN when nobody can type in the terminal.
- `sudo systemctl enable --now chrome-remote-desktop@$USER`
- The desktop is X display `:20`.  Start Chiaki there and put `DISPLAY=:20` in the config file.
- On this virtual display Chiaki may not draw the video, but the keys still reach the Playstation; watch the race on the TV.

## For best results

- At first, you should monitor the script and tweak the `RACE_TIME` variable until the "Race ending" message is shown the moment you cross the finish line.
  - Every log line has a time, and the "Race start" line says when "Race ending" will be shown.  Compare it with when you cross the finish line (or vice versa) to know how much to adjust `RACE_TIME`.
- You will also need to increase `RACE_TIME` periodically as your engine condition decreases over time, but keep your "peak" time written down because that's what you will set it back to once you do an engine overhaul.

## Changelog

- Initial Release
- Updated for xdotool 3.2 and re-timed for GT7 Update 1.63
- Fork changes:
  - Hold R2 only from 2 seconds after pressing X and release it before the menus
  - Press X twice before the first race, because the start screen hides its menu when left alone
  - Read GT7 telemetry (`PLAYSTATION_IP`): check the race started, end the race at the finish line, quit when the car is stuck, log the position and best lap
  - Web page with live telemetry and credits per hour, with start, stop-after-race and emergency stop buttons; dates in the log
  - Retry the race from the pause menu when the car stays stuck, keep a screenshot on every error and show it on the web page (an unknown screen counts as the race while the telemetry says it runs); read the course map for cars close ahead (`TRAFFIC`), with `inside` and `NITRO` as experiments
  - Read the reward from the credits before and after each race (tesseract), warn when it's short, keep the rewards screens and show the newest on the web page
  - Each lap's time and top speed in the log, a line per race in `RACES_FILE`, and a word when the laps get slower than after the last maintenance (`maintenance-done`, the web page's engine card)
  - With `PILOT=1`, drive on with taps when the car gets stuck, and only quit after `STUCK_GIVE_UP` seconds
  - Steer by the track line from the telemetry, or just log what that would do (`DRIVE`, `gt7-analyze.py track`, `gt7/driver.py`)
  - Go through the screens after the race by looking at them, skipping the scene after the finish (`MENUS`, `gt7-screen.py learn`, `classify`, `to-start`)
  - Fix the presses after the race for the current GT7 (two X fewer, so it no longer goes back into the replay) and hold each menu key exactly `KEYPRESS_LENGTH`
  - A virtual gamepad (`gt7/pad.py`, `gt7-pad.py`, `70-gt7-pad.rules`) to send analog values to Chiaki
  - Record every telemetry packet and screenshots of each menu step for analysis (`TELEMETRY_RECORD`, `SCREEN_RECORD`, `gt7-analyze.py`, `gt7-screen.py`); read the steering angle (heartbeat B) and log the packets received and lost per race
  - Time the race by the clock, drive straight for `STRAIGHT_TIME` after the start, grid start; `RACE_TIME` and `RACE_PRIZE` re-measured
  - Release all keys on any exit and log an error when the stream window disappears
  - Match the window title exactly
  - `start`, `stop`, `status` and `log` commands, a lock against running twice, times in the log, a maintenance reminder
  - Settings from a config file or environment variables
  - Check for missing commands and `DISPLAY` instead of installing packages; `bc` and `wmctrl` are no longer needed

## License & Thanks

- [Gran Turismo 7 Daytona Autopilot Script](https://github.com/transce080/gran-turismo-7-daytona) © 2025 by [Jason Lonsberry](https://github.com/transce080) is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/?ref=chooser-v1).
- This fork by [ryuheitakeda](https://github.com/ryuheitakeda) modifies it under the same license; the changes are listed in the Changelog.
- If you find this script useful, feel free to buy me [coffee](https://www.buymeacoffee.com/transce).
