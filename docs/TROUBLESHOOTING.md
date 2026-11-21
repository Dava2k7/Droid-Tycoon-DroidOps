# Danksy's troubleshooting notes

## Windows says Python is missing

Use the **Windows_Setup.exe** release asset. It contains its own Python runtime and does not use the source launcher's BAT files. GitHub's automatic source ZIP is the project code, not the installed app.

## The controller will not connect

Restart Windows after driver installation. If needed, run the supplied ViGEmBus installer from the app's **Driver** folder, then restart and try **Connect** again. Keep the exact driver error if installation fails. Do not replace unrelated Windows drivers to try to fix it.

## Interval or pulse will not change

Stop Auto Scrap, the mission loop and any turn test first. Click inside the number, type the value and press Enter. Pulse must be shorter than interval. Version 1.0.53 corrected an editor geometry fault that prevented clicks while idle; 1.0.54 includes that change.

## Buttons work, but the left turn does not

Close Fortnite menus and avoid moving the mouse during a test. Set **Lock Input Method as Mouse** to **Off** in Fortnite's Mouse and Keyboard settings, then test with **F10**. Adjust turn duration in the mission settings. Windows axis confirmation does not prove that the game accepted the input.

## Droid Watch reports an error

Copy the full message from the error dialog. Re-select a small notification crop and check that it includes the complete variant and rarity. Offset and negative-coordinate monitor crops are supported; regions over 1.5 million pixels are rejected. Keep additional OCR off while troubleshooting.

## A notification was missed

Check that the exact pair is ticked, the notification was visible and the watched rectangle included both labels. Reduce the crop to the notification bar. Screen capture cannot read a covered, minimised or missing notification. OCR can still miss difficult text; report the pair and a cropped example if you can share one safely.

## No sound

Use **Test Alert**, check the selected pairs, Windows volume and the audio output device. The supplied named recordings include the voice and alarm.

## The window does not fit

DroidOps has a fixed 1080 × 780 main window. Check that the display has enough usable space at the current Windows scaling. A 1080-pixel-wide desktop may still be too small once scaling and the taskbar are accounted for.

## The whole PC restarts

Leave Droid Watch off on that PC. Open the installation folder and run **Collect-Diagnostics.bat**, or use the collector from this source package. Read the report before sharing it. See [restart checks](RESTART_DIAGNOSTICS.md). A full system restart needs Windows fault and hardware evidence; its cause has not been diagnosed here.
