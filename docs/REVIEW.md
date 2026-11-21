# Danksy's release checks

Version **1.0.54**, prepared on **21 November 2026**. This is a Windows testing release.

## Completed locally

- **126 tests passed** on Linux, including real Tesseract fixtures, the capture routine with a substituted desktop boundary, exact notification filters, duplicate suppression, controller cancellation, XInput observation logic and actual Qt layout checks.
- The creator credit was tested through 49 clicks, the reveal on click 50, and its reset. The revealed text is **Created by Dane V**.
- Typed timing and mission-calibration edits, saved preferences, fixed window size, footer clearance and the Copy error dialog passed their Qt checks.
- Ruff lint, formatting and Python compilation checks passed.
- The main-window and watcher screenshots were captured from the actual Qt widgets, without starting a game, controller or scan.
- All cached Windows bundle inputs and the included driver passed their pinned SHA-256 checks. The runtime and vgamepad source are also checked before assembly.
- The 1.0.54 offline installer was compiled with NSIS and its archive was checked. Its exact size, hash and extracted-file comparisons are recorded in `validation/setup-1.0.54.json`.
- The source package includes the current notices, screenshots, build scripts, tests, issue form and release instructions, with build caches and private evidence excluded.

## What those checks cover

The timing fault was reproduced as a one-pixel-wide line editor. The repair gives the actual editor a usable click area. Tests click it, type values, commit them and check saved settings.

The watcher capture check now measures an MSS rectangle as right minus left and bottom minus top. This accepts small crops on offset and negative-coordinate monitors. Oversized areas are rejected and padding stays within budget. The earlier error report did not include the exception, so this defect cannot be called its only possible cause.

The turn test waits for Fortnite to remain active and checks the right-stick state through Windows XInput. Tests cover direction, duration, cancellation and neutral-axis cleanup. Observing an axis in Windows does not prove that Fortnite moved its camera.

The primary OCR soak completed 1,083 cycles over 180.08 seconds with no missed expected pairs in synthetic Kyber Mythic, Diamond Mythic and Rainbow Legendary fixtures. Peak RSS was 79.62 MiB, with a 0.19 MiB warm range and one native thread. This was a Linux recognition test, not a live Windows capture session. The recorded result is in `validation/primary-ocr-linux.json`.

The offline payload contains CPython 3.14.10, 37 pinned dependencies, the native launcher, OCR data, original named alerts, artwork, notices and the driver installer. It also includes the read-only restart collector. The installed app does not install Python packages on first launch.

## Still to check

The GitHub workflow has been prepared but has not run in this repository yet. It is set up to test on Windows Server 2022 and 2025, then build the offline installer on Ubuntu. A successful runner job will not certify every Windows 10/11 gaming PC.

Windows installation and uninstall, ViGEmBus loading, real desktop capture, live notification recognition and actual Fortnite camera response have not been executed here. These need testing on Windows before the release is described as verified.

The reported full-PC restart has not been reproduced or diagnosed. Scanner limits reduce resource use, but cannot establish that the restart is resolved or prevent every operating-system, driver, power or hardware fault. Leave Droid Watch off on an affected machine until its diagnostic report is reviewed.

The optional secondary OCR runtime attempted a Microsoft connection during earlier validation, and a request to disable telemetry did not establish that the connection was prevented. No successful secondary soak is claimed. It stays off by default; see [privacy](../PRIVACY.md).

These notes record the checks and their limits. They are not a security certification or a promise of perfect recognition.
