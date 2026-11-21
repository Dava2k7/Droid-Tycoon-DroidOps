from datetime import datetime, timezone
import wave
from PIL import Image
from droidops.droid_catalog import ALERT_CHOICES
from droidops.resources import asset_path
from droidops.session_alert_history import SessionAlertHistory


def test_every_choice_has_a_readable_sound():
    for pair in ALERT_CHOICES:
        with wave.open(
            str(asset_path("droid_alerts/" + pair.lower().replace(" ", "_") + ".wav"))
        ) as wav:
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2
            assert 9 < wav.getnframes() / wav.getframerate() < 20


def test_supplied_artwork_has_transparency_and_icon_sizes():
    image = Image.open(asset_path("hero_droid.png"))
    assert image.mode == "RGBA"
    assert image.getextrema()[-1] == (0, 255)
    icon = Image.open(asset_path("app.ico"))
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes()


def test_session_history_clears_and_does_not_leak_between_instances():
    first = SessionAlertHistory()
    first.record("Kyber Mythic", now=datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc))
    assert first.entries()[0].timestamp == "21/11/2026 12:00:00"
    assert len(SessionAlertHistory()) == 0
    first.clear()
    assert len(first) == 0
