"""Exercise the real capture loop with a controlled desktop API boundary."""

from types import SimpleNamespace
import threading

import pytest

from droidops import droid_alert as scanner


@pytest.mark.parametrize(
    "region,bounds,expected",
    [
        ((2500, 700, 3550, 850), (1920, 0, 3840, 1080), (2452, 652, 3598, 898)),
        ((-3500, -600, -2300, -450), (-3840, -1080, -1920, 0), (-3548, -648, -2252, -402)),
        ((0, 0, 1500, 1000), (0, 0, 1920, 1080), (0, 0, 1500, 1000)),
    ],
)
def test_capture_accepts_offset_crops_and_keeps_padding_within_budget(
    monkeypatch, region, bounds, expected
):
    cancelled, finished = threading.Event(), threading.Event()
    grabs, published = [], []
    frame = object()

    class Desktop:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def grab(self, area):
            grabs.append(area)
            return frame

    visibility = SimpleNamespace(visible_window=lambda area: 41, area_clear=lambda *a: True)
    monkeypatch.setattr(scanner, "MSS", Desktop)
    monkeypatch.setattr(scanner, "FortniteVisibility", lambda identify: visibility)
    monkeypatch.setattr(scanner, "client_area", lambda hwnd: bounds)
    worker = SimpleNamespace(
        is_fortnite_window=lambda hwnd: True,
        visibility_changed=SimpleNamespace(emit=lambda *a: None),
    )

    def publish(item):
        published.append(item)
        cancelled.set()
        finished.set()

    scanner.DroidAlert.capture_frames(worker, region, cancelled, finished, publish)
    assert grabs == [expected]
    assert published[0][1][2] == expected
    assert published[0][2] is frame


def test_invalid_crop_reports_error_without_capturing(monkeypatch):
    grabs, published = [], []

    class Desktop:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def grab(self, area):
            grabs.append(area)

    monkeypatch.setattr(scanner, "MSS", Desktop)
    monkeypatch.setattr(
        scanner,
        "FortniteVisibility",
        lambda identify: SimpleNamespace(visible_window=lambda area: 41),
    )
    worker = SimpleNamespace(is_fortnite_window=lambda hwnd: True)
    scanner.DroidAlert.capture_frames(
        worker, (5000, 5000, 9000, 9000), threading.Event(), threading.Event(), published.append
    )
    assert grabs == []
    assert len(published) == 1
    assert isinstance(published[0], ValueError)
    assert "too large" in str(published[0])
