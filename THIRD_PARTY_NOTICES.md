# Third-party notices

Danksy's MIT licence applies to the application code. It does not replace the licences of bundled dependencies or their data.

| Component | Upstream project / terms |
|---|---|
| PySide6, Shiboken6 and Qt | Qt for Python; LGPL v3 or upstream commercial terms, with associated Qt module notices |
| Tesserocr / Tesseract / Leptonica | Upstream tesserocr, Tesseract and Leptonica notices distributed with their wheels |
| Tesseract English data | Apache 2.0; see `droidops/assets/tessdata/` |
| RapidOCR and included OCR models | RapidOCR / upstream PaddleOCR model notices |
| ONNX Runtime | Microsoft ONNX Runtime notices |
| OpenCV | OpenCV and bundled codec/library notices |
| Pillow, NumPy, MSS and other Python dependencies | Their distributed licence files and package metadata |
| ViGEm client / ViGEmBus | Upstream controller framework terms; the included ViGEmBus 1.22.0 driver is BSD-3-Clause |
| Droid Credit Symbols font subset | SIL Open Font License 1.1; see the font attribution and licence beside the font |
| PyInstaller bootloader | Upstream PyInstaller licence with its bootloader distribution exception |

The build gathers available installed dependency licence files and exact versions into `third-party/` inside the frozen application's `_internal` directory. Qt's LGPL/GPL licence texts are also retained in this repository's `third_party/` folder and copied into the distribution. Review the inventory when dependency versions change; metadata alone is not a substitute for a required full notice.

Qt is dynamically distributed. The application licence does not limit any rights granted for Qt, the font, the driver or other third-party components. Upstream sources and terms are available from:

- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/
- https://doc.qt.io/qtforpython-6/licenses.html
- https://github.com/tesseract-ocr/tessdata_fast/
- https://github.com/RapidAI/RapidOCR
- https://github.com/microsoft/onnxruntime
- https://github.com/opencv/opencv
- https://github.com/nefarius/ViGEmBus
- https://github.com/yannbouteiller/vgamepad

No third-party copyright or attribution notices are transferred to Danksy.

## Offline Windows distribution

The offline installer includes CPython 3.14.10 with its PSF licence, Windows dependency wheels with their original dist-info notices, and the unmodified ViGEmBus installer. The executable entry point uses pip's bundled distlib Windows launcher; its licence remains in the supplied Python runtime. NSIS installer notices are supplied in third_party/NSIS-COPYRIGHT.txt. The application's MIT licence does not replace these third-party terms.
