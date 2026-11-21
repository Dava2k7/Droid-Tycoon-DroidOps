# Danksy DroidOps restart checks

If the whole PC switches off or restarts, leave Droid Watch off on that PC while collecting evidence. An unexpected restart does not identify its cause by itself. A Windows stop error, driver failure or hardware/power problem needs different evidence from an ordinary application crash.

1. Extract the diagnostic package fully.
2. Double-click **Collect-Diagnostics.bat**. It does not need DroidOps or Fortnite running.
3. The report opens in Notepad. It is saved under `%LOCALAPPDATA%\DroidTycoonAutoClicker\diagnostics`, named **DroidOps-Diagnostics-date-time.txt**.
4. Review it before sharing. It includes CPU, graphics driver, memory, recent Windows fault events and the latest watcher log if available. It excludes serial numbers and dump contents; user-profile and computer names are redacted.
5. Send the report to whoever is investigating the restart. Missing or access-denied sections are recorded; do not repeatedly start the watcher to reproduce a shutdown.

The collector reads system information and writes its local report. It does not install software, change Windows settings or upload data. Its temporary PowerShell execution-policy override applies only to that process.

Version 1.0.51 limits native OCR threads, inference image sizes, capture buffers and the scanner's monitored memory use. These are application safeguards, not proof that the original restart is resolved. Windows capture, driver compatibility and the affected PC still require testing.

Microsoft's reference: https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/event-id-41-restart
