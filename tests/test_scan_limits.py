from types import SimpleNamespace
import pytest

from droidops.scan_limits import (
    MAX_WORKER_BYTES,
    configure_native_threads,
    scanner_over_budget,
    validate_capture_region,
)


@pytest.mark.parametrize("region", [None, (0, 0, 0, 90), (0, 0, 1920, 1080), (0, 0, -10, 40)])
def test_oversized_or_invalid_area_rejected_before_capture(region):
    with pytest.raises(ValueError, match="notification bar"):
        validate_capture_region(region)


def test_notification_crop_preserved_including_negative_monitor_coordinates():
    assert validate_capture_region((-1920, 100, -320, 180)) == (-1920, 100, -320, 180)


@pytest.mark.parametrize(
    "region", [(2500, 700, 3550, 850), (-3500, -600, -2300, -450), (100000, 100000, 100800, 100120)]
)
def test_same_small_crop_is_valid_regardless_of_desktop_offset(region):
    assert validate_capture_region(region) == region


def test_large_crop_is_rejected_even_when_its_bottom_right_is_negative():
    with pytest.raises(ValueError, match="too large"):
        validate_capture_region((-6000, -6000, -2000, -2000))


def test_native_threads_override_existing_all_core_setting(monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "32")
    configure_native_threads()
    import os

    assert os.environ["OMP_NUM_THREADS"] == os.environ["OMP_THREAD_LIMIT"] == "1"


def test_memory_monitor_checks_only_owned_scanner_pid(monkeypatch):
    import psutil

    seen = []

    def process(pid):
        seen.append(pid)
        return SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=MAX_WORKER_BYTES + 1))

    monkeypatch.setattr(psutil, "Process", process)
    assert scanner_over_budget(SimpleNamespace(pid=123))
    assert seen == [123]


def test_exited_scanner_does_not_fail_memory_check(monkeypatch):
    import psutil

    def missing(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", missing)
    assert not scanner_over_budget(SimpleNamespace(pid=123))


def test_disabled_secondary_engine_does_not_import_native_runtime(monkeypatch):
    import builtins
    from droidops.hybrid_droid_detection import RapidFallback

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in ("onnxruntime", "rapidocr"):
            raise AssertionError("Disabled engine must not load a third-party runtime")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    engine = RapidFallback(enabled=False)
    assert not engine.enabled
    assert engine.read(None, None, None, None) == []
