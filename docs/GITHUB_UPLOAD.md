# Danksy's GitHub upload guide

This package is ready to become a public source repository. Upload the source folder first, then attach the Windows installer to a testing release. The source and the installer are separate downloads.

## 1. Extract the package

Download **Danksy_DroidOps_GitHub_Ready.zip** and choose **Extract All**. Open **Danksy-DroidOps** inside it. You should see `README.md`, `LICENSE`, `droidops`, `scripts`, `tests`, `packaging`, `docs` and `.github`.

Keep the screenshots in `docs/images`. The README will display them automatically once the source is uploaded.

## 2. Create the repository

1. Sign in to GitHub and open [Create a repository](https://github.com/new).
2. Choose your account and use **DroidOps** as the repository name.
3. Suggested description: **Danksy's Windows companion for Droid Tycoon: Droid Watch, Auto Scrap and the CB-23 mission loop.**
4. Choose **Public** to keep the source open.
5. Leave the new README, licence and `.gitignore` options off. They are included in this package.
6. Create the repository and copy its HTTPS address.

## 3. Upload with GitHub Desktop

1. Install [GitHub Desktop](https://desktop.github.com/download/) and sign in.
2. In its Git settings, use **Danksy** as the public commit name if preferred. Use your actual no-reply email from [GitHub email settings](https://github.com/settings/emails) if you want your personal address kept private.
3. Select **File → Clone repository → URL**, paste the address and choose a local folder.
4. Open the cloned folder in Explorer. Copy the **contents** of `Danksy-DroidOps` into it, including `.github`, `.gitignore` and `.gitattributes`. Keep the clone's `.git` folder.
5. Check that `README.md` is at the repository root, rather than inside another nested folder.
6. Return to Desktop and use **Prepare DroidOps 1.0.54 testing release** as the commit summary.
7. Click **Commit to main**, then **Publish branch** or **Push origin**.
8. Open the repository page and check the README, both screenshots and source folders.

Do not commit the roughly 412 MB installer or its extracted Python environment to the source repository. The installer belongs in release assets. The source package already excludes build folders, caches, local logs and private notification evidence.

## 4. Run the build checks

Open **Actions → Windows build**. A push to `main` starts it; you can also use **Run workflow**.

The workflow runs the source tests and a short primary-OCR check on Windows Server 2022 and 2025, using Python 3.14. It then assembles the pinned Windows runtime and dependencies and compiles the offline NSIS installer on Ubuntu. It checks the installer archive and writes its checksum. It does not publish anything automatically.

After a successful run, download **Danksy-DroidOps-Windows** from its Artifacts section while signed into GitHub. Extract it to find:

- `Danksy_DroidOps_1.0.54_Windows_Setup.exe`
- `SHA256SUMS.txt`
- `RELEASE_NOTES.md`

The prepared workflow still needs its first GitHub run. A runner check does not test Fortnite or certify every home PC. If a step fails, keep its error and fix that before distributing a new build.

A fresh build can have a different checksum from the installer already supplied here. Always use the checksum produced alongside the particular EXE you attach.

## 5. Test the actual program

Install Setup on your own Windows PC, then check:

- Desktop and Start menu shortcuts, startup and the fixed window layout.
- Interval and pulse edits while idle, and saved values after reopening.
- Controller connection, Test Input, Stop and F8.
- F10 left-turn calibration in Fortnite, including actual camera movement.
- Droid Watch start/stop, selected-pair recognition, unticked pairs and Test Alert.
- Normal app shutdown and Windows uninstall.

On a PC that has restarted, leave Droid Watch off and collect diagnostics first. Read [restart checks](RESTART_DIAGNOSTICS.md). The original full-PC restart is unresolved.

## 6. Create the release

1. Open **Releases → Draft a new release**.
2. Create tag **v1.0.54**, targeting the commit used for your chosen build.
3. Use **Danksy DroidOps 1.0.54** as the title.
4. Paste the text from [release notes](RELEASE_NOTES_1.0.54.md).
5. Attach the Setup EXE and its matching `SHA256SUMS.txt`.
6. Tick **Set as a pre-release** while live Windows testing remains outstanding.
7. Publish when ready, then share the release page.

You can use the supplied 1.0.54 installer and its supplied checksum for this first testing release, provided the uploaded source is this matching version. Do not mix an older 1.0.53 EXE with a 1.0.54 release.

GitHub adds source archives separately. People who only want to install DroidOps should download **Windows_Setup.exe**, rather than **Source code**.

## Repository details

Suggested topics: `droidops`, `droid-tycoon`, `windows`, `desktop-app`, `python`, `pyside6`.

The MIT licence allows people to use and change their own copies. It does not let them push into the official repository. Keep write access limited to people you trust and review pull requests before merging.

For later updates, edit the same local clone, update the version and notes, commit and push. Wait for a successful build, test its output and create a new release tag. Do not reuse an existing tag for changed files.

Official references: [create a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository), [clone with Desktop](https://docs.github.com/en/desktop/adding-and-cloning-repositories/cloning-and-forking-repositories-from-github-desktop), [run a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow), [manage releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
