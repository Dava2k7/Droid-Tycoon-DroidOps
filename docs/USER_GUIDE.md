# Danksy's DroidOps guide

## Installation

1. Download **Danksy_DroidOps_1.0.54_Windows_Setup.exe** from the GitHub release assets.
2. Run Setup and allow the Windows administrator prompt. Choose the installation folder and let it finish.
3. Setup includes Python and the app's libraries. It installs the bundled virtual Xbox controller driver if it is missing. Restart Windows if asked.
4. Open **Danksy DroidOps** from the desktop or Start menu. Click **Connect** to create the virtual controller.

You do not need a separate Python installation. Any Python you already use for other projects can stay installed. Setup adds an uninstaller to Windows Installed apps. Removing DroidOps keeps per-user settings and logs, and leaves the shared controller driver in place.

The installer is not code-signed by Danksy. Windows may show an unrecognised publisher warning. Check the source and release checksum before choosing whether to run a downloaded copy; there is no need to switch off Windows security.

## Auto Scrap and timing

Choose a controller input, then set **Interval / ms** and **Pulse / ms**. Interval is the time between pulses; pulse is how long the input is held. For example, 500 ms and 45 ms sends a short press every half-second.

Click the number, type your value and press Enter. Pulse must be shorter than interval. These values are saved between launches. Stop controller automation before changing them. **Test Input** sends one pulse. **Auto Scrap** starts repetition. **Stop** or **F8** stops controller automation.

## Droid Watch

1. Open **Droid Watch** and choose **Set Notification Window**.
2. Switch to Fortnite within the four-second countdown.
3. Select a tight rectangle around the complete Sandcrawler notification, including the variant and the rarity beside the droid name.
4. Tick each exact variant/rarity combination you want announced.
5. Press **Start Watching**. Use the same dialog to stop it.

The saved rectangle follows the game window. The watched area must remain visible, even when using another application. Minimise or cover Fortnite and screen-based monitoring pauses. It cannot detect a notification that the game never shows.

All five rarities are selectable across Default, Gold, Diamond, Rainbow, Beskar, Galactic, Stellar, Kyber and Scourge. Stella is accepted as Stellar. Default and Gold require a visible game notification. An alert needs both a recognised variant and rarity that you have selected. Unknown or incomplete labels do not trigger generic rarity warnings.

The named recording speaks, plays the existing seven-second alarm, then repeats the name. **Test Alert** checks playback. **History** shows this launch's detected alerts and clears when the app closes.

Keep the watched area small. Optional evidence screenshots and additional OCR are off by default for new settings. The extra OCR engine uses more memory and its third-party runtime may contact Microsoft. Read [privacy](../PRIVACY.md) before enabling it.

## CB-23 mission loop

Stand at the mission machine, open **CB-23 Loop** and set the mission menu position, cycle timing and camera turn duration for your game settings. Use **Save Settings** to keep them.

Test the turn before starting a long loop. Click **Test Left Turn**, return to Fortnite, close menus and stop moving the mouse. The test waits for the game to stay active for one second. **F10** starts the saved test from inside the game; **F8** cancels it. Adjust the duration until the camera reaches the intended position.

If buttons work but the camera does not, check Fortnite **Settings → Mouse and Keyboard → Lock Input Method as Mouse → Off**. This is a setting to check, rather than a confirmed explanation for every failed turn. [Epic's controller troubleshooting](https://www.epicgames.com/help/c-34254770/c-33726977/a20977468).

The status message can confirm that Windows reported right-stick movement. It cannot confirm the game moved the camera or selected the crate. Check that yourself. Mouse camera mode needs the game in the foreground; Xbox mission mode supports background input. **F9** starts the saved loop. Droid Watch has its own stop control.

## Window and status

The main window stays at **1080 × 780**. Drag its header to move it. Maximise and resizing are disabled. Settings and history open separately.

| Watcher status | Meaning |
|---|---|
| On | Monitoring is running |
| Delayed | Recognition is behind the captured frames; try a smaller crop |
| Stalled | The scanner has stopped reporting progress |
| Paused | The selected game area is hidden or unavailable |
| Error | Read the full error and use Copy error when reporting it |

Settings are stored per Windows user. Local files are under `%LOCALAPPDATA%\DroidTycoonAutoClicker`; these include rotating logs, learned labels and optional evidence screenshots. Nothing in the app uploads captured frames or session history.

## Reporting a problem

Please include the app version, Windows version, what you clicked and the exact error. If camera input fails, say whether **Test Input** still works. Do not post private screen content or unreviewed diagnostic reports.

If the whole PC turns off or restarts, leave Droid Watch off and follow [restart checks](RESTART_DIAGNOSTICS.md). The cause of the reported restart has not been established. No release check guarantees compatibility with every PC.
