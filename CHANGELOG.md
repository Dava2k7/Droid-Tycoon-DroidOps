# Changelog

## 1.0.54 (Windows testing release)

- Change the hidden creator credit to “Created by Dane V”.
- Include the read-only restart collector in the offline installation.
- Add current main-window and Droid Watch screenshots to the README.
- Update installation, troubleshooting and release instructions under Danksy.
- Add hash-checked bundle downloads and an offline NSIS GitHub build.
- Keep portable UI tests independent of a system controller driver on Windows.

## 1.0.53 (Windows testing candidate)

- Repair the one-pixel timing editors, accept normal mouse/keyboard edits and save interval/pulse preferences.
- Confirm right-stick movement through Windows XInput during calibration and retain the result after the test.
- Explain Fortnite input-method conflicts in calibration; retain foreground Mouse mode and background Xbox mode.
- Add a fully bundled offline Windows payload, native executable launcher and NSIS Setup.exe with shortcuts/uninstall support.
- Include the existing controller-driver installer and install it when absent.

## 1.0.52 (testing candidate)

- Calculate watched-area size from right minus left and bottom minus top, matching MSS desktop coordinates.
- Accept small notification crops on offset and negative-coordinate monitors; keep padding inside the capture budget.
- Show the full scanner failure in a non-modal message with a Copy error button.
- Preserve scanner exception types and report event-bridge failures explicitly.
- Add capture-loop regression tests and error-message/copy checks.

## 1.0.51 (testing candidate)

- Remove generic Possible Mythic/Legendary warnings, settings, test controls and audio files. Announce only recognised, selected variant/rarity pairs.
- Wait for Fortnite to remain active for one second before sending a test left turn; cancel with F8.
- Keep DroidOps visible when starting from the mission settings dialog.
- Limit native OCR threads, CPU inference sizes, capture buffers and evidence queues.
- Reject notification areas larger than 1.5 million pixels and monitor the scanner's 512 MB memory budget.
- Add cancellable OCR cooldowns and explicitly disable ONNX Runtime telemetry.
- Leave experimental secondary OCR off by default after an external telemetry connection blocked validation; retain primary OCR and learned visual labels.
- Add read-only Windows restart diagnostics, OCR soak checks and two Windows runner compatibility jobs.
- Include a complete GitHub Desktop upload and pre-release guide.
- Preserve existing artwork, the fixed main window, voices and alarms.
- Retry original colour pixels when grayscale misses labels, covering a reproduced blue-background Diamond Mythic failure.

## 1.0.50

- Package DroidOps as an installable Python application with an isolated Windows build.
- Add executable version information, a Windows installer, portable release archives and checksums.
- Add GitHub Actions, maintainer documentation, unit tests and MIT licensing under Danksy.
- Stop scanner bridge workers and timers when closing the application.
- Make diagnostic screenshot capture opt-in for new settings.
- Verify that both OCR engines recognise their synthetic test label during frozen-app checks.
- Keep the compact droid interface, existing audio and controller features.

## 1.0.49

- Add the personalised droid artwork and framed app icon.
- Remove mouse captions and centre the larger Danksy signature beneath the artwork.

## 1.0.48

- Fix the main window at 1080 × 780 and correct footer/title-control spacing.

## 1.0.47

- Add all rarity/variant combinations and suppress generic warnings for readable unticked variants.
