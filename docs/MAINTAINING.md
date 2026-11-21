# Danksy's build notes

## Standard release build

The **Windows build** GitHub workflow runs Windows compatibility checks, then builds the offline Windows Setup with NSIS on Ubuntu. It uploads an artifact but does not publish a release. The [upload guide](GITHUB_UPLOAD.md) covers that last step.

The installed app uses the pinned **Windows x64 CPython 3.14.10** runtime. The Python used to assemble the files on the build host is separate; Python 3.12 or newer can run these build scripts. Neither the assembler nor the installer runs pip on an end user's PC.

Pinned inputs are recorded in:

| File | Contents |
|---|---|
| `packaging/python-runtime.json` | Python runtime URL, version and SHA-256 |
| `packaging/windows-bundle-lock.json` | Windows wheel URLs, versions and SHA-256 values |
| `packaging/vgamepad-source.json` | vgamepad source archive URL and SHA-256 |
| `packaging/driver.json` | Included ViGEmBus driver version and SHA-256 |

Download the build inputs:

```sh
python scripts/Fetch-Windows-Bundle.py --output bundle-inputs
```

The script checks every file against its pinned SHA-256, including the included driver. Existing correct downloads are reused. To check a cached set without downloading anything, add `--verify-only`.

Assemble the Windows payload:

```sh
python scripts/Assemble-Windows-Bundle.py --wheels bundle-inputs/wheels --resolution packaging/windows-bundle-lock.json --runtime bundle-inputs/python-runtime.nupkg --vgamepad bundle-inputs/vgamepad.tar.gz --output offline-payload
```

With NSIS installed, compile Setup. On Linux, use the path returned by `command -v makensis`; on Windows, pass the full path to `makensis.exe`.

```sh
python scripts/Build-Offline-Setup.py --payload offline-payload --compiler /usr/bin/makensis --output Danksy_DroidOps_1.0.54_Windows_Setup.exe
```

An extracted NSIS installation may also need `--nsis-dir` pointing to its data directory. The compiler creates a native Windows installer on either build host. Compilation and archive integrity do not establish that installation or live game input works; test those on Windows.

The payload uses a relative distlib EXE launcher and its bundled `runtime/pythonw.exe`. It retains original dependency notices, native DLLs and replaceable Qt libraries. Setup installs the supplied driver only when its service is missing, adds shortcuts and registers an uninstaller. Uninstall preserves the shared driver and per-user settings/logs.

## Source checks

Use an isolated environment. On Windows, set `VGAMEPAD_SKIP_VIGEMBUS_INSTALL=true` before installing development dependencies so dependency setup does not run a driver installer.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check droidops scripts tests
python -m ruff format --check droidops scripts tests launch.py
```

Native OCR tests also need Tesseract/tesserocr and psutil; these are in `requirements-windows-lock.txt` for Windows. The UI tests load the view without a virtual controller and send no game inputs. They check actual Qt widgets and do not replace driver tests.

The primary OCR soak is `python scripts/Soak-Scanner.py --seconds 180`. Default checks exclude the optional secondary runtime. Read [privacy](../PRIVACY.md) before opting into tests that load it.

## Alternate PyInstaller build

The older Windows-only build remains available through **Build-Windows.bat**, using 64-bit Python 3.12 and Inno Setup 6 or 7. It creates a frozen application, an optional-driver Inno installer and a portable ZIP. These use different filenames and a different build path from the standard offline NSIS release. They are not the files produced by the current GitHub workflow.

`-VerificationProfile Build` skips display-dependent capture checks; the local default also checks capture. Do not treat either as proof of Fortnite input. See the build script for runtime check reports.

## Releasing an update

1. Change `droidops/__init__.py` and the fallback versions in both installer definitions.
2. Update the changelog, user instructions, versioned release notes and screenshots when needed.
3. Run source checks, build Setup, test the archive and generate a fresh SHA-256 file for that exact EXE.
4. Install on Windows and check startup, controller connect/stop, timing edits, turns, watcher start/stop, alerts, shutdown and uninstall.
5. Keep the release marked as a pre-release while relevant Windows checks remain outstanding.
6. Upload only release assets to Releases. Keep runtimes, local logs, private evidence and build caches out of source control.

Review third-party notices when dependencies change. Keep Qt libraries replaceable and preserve the source/licence rights required by their terms. The application's MIT licence does not replace dependency licences.

The current prepared workflow has not yet run on GitHub. It exercises Windows Server 2022 and 2025, not every Windows 10/11 gaming PC. The reported full-PC restart is unresolved.

Build references: [NSIS](https://nsis.sourceforge.io/Docs/), [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html), [GitHub Actions](https://docs.github.com/en/actions), [Inno Setup](https://jrsoftware.org/isinfo.php).
