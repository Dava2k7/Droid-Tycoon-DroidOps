"""Resource limits shared by the scanner and its supervising process."""

import os

MAX_CAPTURE_PIXELS = 1_500_000
MAX_WORKER_BYTES = 512 * 1024 * 1024


def configure_native_threads():
    """Apply before native OCR imports in the dedicated scanner process."""
    for name in (
        "OMP_THREAD_LIMIT",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"


def validate_capture_region(region):
    """Validate MSS's (left, top, right, bottom) desktop coordinates."""
    if not region or len(region) != 4:
        raise ValueError("Select the Sandcrawler notification bar before starting Droid Watch.")
    left, top, right, bottom = region
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0 or width * height > MAX_CAPTURE_PIXELS:
        raise ValueError(
            "The Droid Watch area is too large. Select only the Sandcrawler notification bar "
            "in Droid Watch settings, then retry (maximum 1.5 million pixels)."
        )
    return region


def scanner_over_budget(process):
    """Inspect only the scanner PID owned by this application; never the game."""
    import psutil

    try:
        return psutil.Process(process.pid).memory_info().rss > MAX_WORKER_BYTES
    except psutil.NoSuchProcess:
        return False


def rapid_cpu_parameters():
    return {
        "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_cuda": False,
        "EngineConfig.onnxruntime.use_dml": False,
        "EngineConfig.onnxruntime.use_cann": False,
        "EngineConfig.onnxruntime.use_coreml": False,
        "Global.max_side_len": 1280,
        "Global.use_cls": False,
        "Det.limit_type": "max",
        "Det.limit_side_len": 960,
        "Rec.rec_batch_num": 4,
    }
