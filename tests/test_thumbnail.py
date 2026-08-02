"""Tests for thumbnail path helpers and guards."""

from pathlib import Path

import pytest

from audio_video_sync.thumbnail import ALL_STYLES, IMAGE_SUFFIXES, _save_image


def test_all_styles():
    assert set(ALL_STYLES) == {"clean", "gradient"}


def test_output_path_disambiguation_for_multi_style():
    output = Path("/tmp/cover.png")
    styles = list(ALL_STYLES)
    paths = [
        output.with_name(f"{output.stem}_{s}{output.suffix}")
        for s in styles
    ]
    assert [p.name for p in paths] == ["cover_clean.png", "cover_gradient.png"]


def test_save_image_rejects_video_extension(tmp_path):
    from PIL import Image

    img = Image.new("RGB", (8, 8), color=(10, 20, 30))
    target = tmp_path / "out.mp4"
    with pytest.raises(RuntimeError, match="Unsupported thumbnail extension"):
        _save_image(img, target)
    assert not target.exists()


def test_image_suffixes_include_common_formats():
    assert {".png", ".jpg", ".jpeg", ".webp"} <= IMAGE_SUFFIXES
