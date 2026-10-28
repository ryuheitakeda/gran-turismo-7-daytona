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

- `RACE_TIME` (default 800): seconds from the "Race start" log line until you cross the finish line.  It was measured with the grid start above; you will need to set it according to your vehicle speed.
  - If you're not sure, start with the time it takes to rubber-band the race.
- `STRAIGHT_TIME` (default 15): seconds to drive straight after the start before steering towards the wall.
- `RACE_PRIZE` (default 9705000): only used to total the credits in the log.  If you use a different car or setup, set it to the reward you get.
- `MAINTENANCE_RACES` (default 20): log a reminder to check the oil and engine every that many races; 0 turns it off.
- `QUICKPRESS_LENGTH` (default 0.01) and `KEYPRESS_LENGTH` (default 0.08): how long the steering taps and the menu presses last, in seconds.  The window is looked up on every key press, which adds about 0.04 seconds to each tap; the steering is tuned with that included.
- `WINDOW_NAME` (default `^Chiaki \| Stream$`): the Chiaki stream window title as an xdotool regular expression (case-insensitive).
- `ANALOG_L__R`, `DPAD_R`, `KEY_R2`, `KEY_X`: keys that MUST match your Chiaki key config.  The defaults are Chiaki's default keys.
- `LOG_FILE` (default `~/gt7-daytona.log`) and `LOCK_FILE` (default `~/.cache/gt7-daytona.lock`): used by the background commands below.

## Directions

- Start your Playstation and start Gran Turismo 7.
- Start Chiaki and connect to your Playstation.
- With your low PP tune selected, start a custom race at Daytona and load the custom race settings.
- Enter the race itself.  Switch to your high PP tune.
- With the arrow on the Start button, start the script.
  - The start screen hides its menu after a while without input, and the first X press only brings it back.  So before the first race the script presses X twice, 2 seconds apart; if the menu was showing, the second press lands on the loading screen.
  - `./gt7-daytona.sh` runs it in the terminal.  When you're done, exit the script by pressing `CTRL+C`.
  - `./gt7-daytona.sh start` runs it in the background and writes the log to `~/gt7-daytona.log`.  Use `./gt7-daytona.sh status`, `./gt7-daytona.sh log` and `./gt7-daytona.sh stop` to check on it and stop it.
  - From an SSH session, set `DISPLAY` to the desktop that shows Chiaki (e.g. `DISPLAY=:20` in the config file).
- Only one copy of the script can run at a time.
- The script releases every key it holds when it quits, whether by `CTRL+C`, `stop`, `kill` or an error.  Only `kill -9` can leave R2 held down in Chiaki; release it with `xdotool search --name '^Chiaki \| Stream$' keyup 4`.
- If the Chiaki stream window disappears (e.g. the stream disconnects), the script logs an error and quits.

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
