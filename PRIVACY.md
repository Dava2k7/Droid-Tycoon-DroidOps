# Danksy DroidOps privacy

DroidOps reads pixels from a user-selected, visible game region and recognises text locally. It does not require an account, upload captured frames or publish alert history. The default watcher does not load the optional ONNX runtime.

Settings are stored per Windows user. Alert history exists in memory and clears when the program closes. Rotating diagnostic logs, learned label shapes and optional notification-area screenshots are stored beneath `%LOCALAPPDATA%/DroidTycoonAutoClicker`.

Notification screenshots are disabled by default for new settings. Enabling the evidence checkbox keeps a bounded local collection for troubleshooting. Existing saved choices are preserved during updates. Delete the relevant local folders to remove stored evidence and shapes.

The dependency installer uses the Python package index during builds. Additional OCR is experimental and off by default, including on upgrades without an explicit preference. Its third-party ONNX runtime attempted a Microsoft telemetry connection during validation; that test was blocked. The program requests telemetry to be disabled before model loading, but this was insufficient to establish that no connection occurs. Enabling the additional OCR may contact Microsoft. Missing model configurations may also cause the secondary dependency to retrieve a model. The application has no feature to send screenshots or recognised text to an online service.

Reports or screenshots submitted to GitHub are shared by the person submitting them. Check them for personal information first.
