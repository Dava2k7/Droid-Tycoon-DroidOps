"""Real Tesseract regressions for notification colours; no game or network required."""

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from droidops.scan_limits import configure_native_threads


@pytest.fixture(scope="module")
def ocr():
    configure_native_threads()
    native = pytest.importorskip("tesserocr")
    from droidops.resources import asset_path

    with native.PyTessBaseAPI(
        path=str(asset_path("tessdata")),
        lang="eng",
        oem=native.OEM.LSTM_ONLY,
        psm=native.PSM.SPARSE_TEXT,
    ) as engine:
        yield engine


@pytest.mark.parametrize("background", [(8, 12, 20), (45, 70, 100), (55, 25, 16)])
@pytest.mark.parametrize("green", [171, 217])
@pytest.mark.parametrize(
    "variant,rarity", [("Kyber", "Mythic"), ("Diamond", "Mythic"), ("Rainbow", "Legendary")]
)
def test_coloured_notifications_keep_variant_and_rarity(ocr, background, green, variant, rarity):
    from droidops.droid_alert import recognise

    font_path = (
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
        if os.name == "nt"
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    )
    if not font_path.is_file():
        pytest.skip("Notification regression font unavailable")
    image = Image.new("RGB", (1280, 120), background)
    ImageDraw.Draw(image).text(
        (12, 35),
        f"{variant} Droid {rarity} has spawned at the Sandcrawler",
        font=ImageFont.truetype(str(font_path), 30),
        fill=(255, green, 220),
        stroke_width=1,
        stroke_fill="black",
    )
    assert f"{variant} {rarity}" in {m.pair for m in recognise(ocr, None, (0, 0), image=image)}
