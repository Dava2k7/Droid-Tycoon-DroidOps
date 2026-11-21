from PyInstaller.utils.hooks import collect_delvewheel_libs_directory, copy_metadata

# The Windows wheel loads native OCR libraries from its adjacent .libs directory.
datas, binaries = collect_delvewheel_libs_directory("tesserocr", datas=copy_metadata("tesserocr"))
