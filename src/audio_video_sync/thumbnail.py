"""Thumbnail generation: extract video frame and add styled text overlay."""

import platform
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Literal, Optional

from loguru import logger
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat

ThumbnailStyle = Literal["clean", "gradient"]
ALL_STYLES: tuple[ThumbnailStyle, ...] = ("clean", "gradient")

# YouTube recommended max long-edge for custom thumbs (keeps files under ~2MB)
DEFAULT_MAX_EDGE = 1280

FONT_SEARCH = [
    ("/System/Library/Fonts/Supplemental/Futura.ttc", 4),  # Futura Bold
    ("/System/Library/Fonts/Avenir Next.ttc", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]


def _get_font(size: int) -> ImageFont.ImageFont:
    for path, index in FONT_SEARCH:
        if not Path(path).exists():
            continue
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    raw = result.stdout.strip()
    if not raw or raw.upper() == "N/A":
        raise RuntimeError(f"Could not determine duration of {video_path.name}")
    return float(raw)


def extract_frame(video_path: Path, timestamp: float) -> Image.Image:
    """Extract a single frame from video as a PIL Image."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Frame extraction failed: {result.stderr.decode()}")
    if not result.stdout:
        raise RuntimeError(
            f"No frame at {timestamp:.1f}s — check that --time is within the video"
        )
    return Image.open(BytesIO(result.stdout))


def _is_dark(image: Image.Image) -> bool:
    """Check if the center band of the image is dark."""
    w, h = image.size
    crop = image.crop((0, int(h * 0.3), w, int(h * 0.7)))
    avg = ImageStat.Stat(crop.convert("L")).mean[0]
    return avg < 140


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    base_size: int,
    min_size: int = 24,
) -> ImageFont.ImageFont:
    """Shrink font until text fits within max_width."""
    size = base_size
    while size > min_size:
        font = _get_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _get_font(min_size)


def _text_layer(
    size: tuple[int, int],
    title: str,
    artist: Optional[str],
    font_size: int,
    color: str,
) -> Image.Image:
    """Render title and optional artist text on a transparent layer."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w, h = size
    max_width = int(w * 0.9)

    title_font = _fit_text(draw, title, max_width, font_size)
    title_y = int(h * 0.45)
    draw.text((w // 2, title_y), title, font=title_font, fill=color, anchor="mm")

    if artist:
        artist_size = max(24, int(font_size * 0.55))
        artist_font = _fit_text(draw, artist, max_width, artist_size)
        # Approximate title height from font size for spacing
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_h = title_bbox[3] - title_bbox[1]
        artist_y = title_y + title_h // 2 + int(font_size * 0.35)
        draw.text(
            (w // 2, artist_y), artist,
            font=artist_font, fill=color, anchor="mm",
        )

    return layer


def _glow(text_layer: Image.Image, shadow_rgb: tuple[int, int, int], radius: int) -> Image.Image:
    """Add a blurred glow behind the text layer."""
    _, _, _, a = text_layer.split()
    shadow = Image.merge("RGBA", (
        Image.new("L", text_layer.size, shadow_rgb[0]),
        Image.new("L", text_layer.size, shadow_rgb[1]),
        Image.new("L", text_layer.size, shadow_rgb[2]),
        a,
    ))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius))

    out = Image.new("RGBA", text_layer.size, (0, 0, 0, 0))
    out = Image.alpha_composite(out, shadow)
    out = Image.alpha_composite(out, shadow)
    return Image.alpha_composite(out, text_layer)


def _style_clean(bg: Image.Image, title: str, artist: Optional[str], font_size: int) -> Image.Image:
    dark = _is_dark(bg)
    color = "#FFFFFF" if dark else "#0a0a0a"
    shadow_rgb = (0, 0, 0) if dark else (255, 255, 255)

    text = _text_layer(bg.size, title, artist, int(font_size * 1.25), color)
    glowed = _glow(text, shadow_rgb, int(font_size * 0.4))

    result = bg.copy().convert("RGBA")
    return Image.alpha_composite(result, glowed)


def _style_gradient(bg: Image.Image, title: str, artist: Optional[str], font_size: int) -> Image.Image:
    w, h = bg.size

    vignette = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(vignette)
    band_top, band_bot = int(h * 0.25), int(h * 0.75)
    band_mid = (band_top + band_bot) // 2
    for y in range(band_top, band_bot):
        dist = abs(y - band_mid) / ((band_bot - band_top) / 2)
        alpha = int(140 * (1 - dist ** 2))
        draw.line([(0, y), (w, y)], fill=(0, 0, 0, max(0, alpha)))

    text = _text_layer((w, h), title, artist, font_size, "#FFFFFF")
    glowed = _glow(text, (0, 0, 0), int(font_size * 0.1))

    result = bg.copy().convert("RGBA")
    result = Image.alpha_composite(result, vignette)
    return Image.alpha_composite(result, glowed)


STYLE_FN = {"clean": _style_clean, "gradient": _style_gradient}


def _resize_max_edge(image: Image.Image, max_edge: int) -> Image.Image:
    w, h = image.size
    longest = max(w, h)
    if longest <= max_edge:
        return image
    scale = max_edge / longest
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return image.resize(new_size, Image.Resampling.LANCZOS)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _save_image(image: Image.Image, path: Path) -> None:
    """Save using format inferred from extension."""
    suffix = path.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise RuntimeError(
            f"Unsupported thumbnail extension '{suffix or '(none)'}' "
            "— use .png, .jpg, or .webp"
        )
    rgb = image.convert("RGB")
    if suffix in (".jpg", ".jpeg"):
        rgb.save(path, "JPEG", quality=90, optimize=True)
    elif suffix == ".webp":
        rgb.save(path, "WEBP", quality=90)
    else:
        rgb.save(path, "PNG", optimize=True)


def open_path(path: Path) -> None:
    """Open a file with the OS default viewer (macOS/Linux/Windows)."""
    system = platform.system()
    if system == "Darwin":
        cmd = ["open", str(path)]
    elif system == "Windows":
        cmd = ["cmd", "/c", "start", "", str(path)]
    else:
        cmd = ["xdg-open", str(path)]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def create_thumbnail(
    video_path: Path,
    title: str,
    artist: Optional[str] = None,
    output: Optional[Path] = None,
    timestamp: Optional[float] = None,
    style: Optional[ThumbnailStyle] = None,
    font_size: int = 72,
    max_edge: int = DEFAULT_MAX_EDGE,
    save_frame: bool = False,
) -> list[Path]:
    """Generate thumbnail(s) from a video frame. Returns paths of created files."""
    if max_edge < 64:
        raise RuntimeError("--max-edge must be at least 64")

    duration = _get_video_duration(video_path)
    if timestamp is None:
        timestamp = duration / 2
        logger.info(f"Video duration: {duration:.1f}s, using frame at {timestamp:.1f}s")
    elif timestamp < 0 or timestamp > duration:
        raise RuntimeError(
            f"Frame time {timestamp:.1f}s is outside video duration {duration:.1f}s"
        )

    logger.info(f"Extracting frame from {video_path.name}...")
    frame = extract_frame(video_path, timestamp)
    logger.info(f"Frame size: {frame.size[0]}x{frame.size[1]}")

    if save_frame:
        frame_path = video_path.parent / f"{video_path.stem}_frame.png"
        frame.save(frame_path)
        logger.info(f"Frame saved: {frame_path.name}")

    frame = _resize_max_edge(frame, max_edge)

    bg = frame.copy()
    bg = bg.filter(ImageFilter.GaussianBlur(8))
    bg = ImageEnhance.Brightness(bg).enhance(0.9)

    scale = frame.size[0] / 1080
    scaled_font = max(24, int(font_size * scale))

    styles: list[ThumbnailStyle] = [style] if style else list(ALL_STYLES)

    artist_label = f" by {artist}" if artist else ""
    logger.info(f'Generating {len(styles)} thumbnail(s): "{title}"{artist_label}')

    outputs: list[Path] = []
    for s in styles:
        if output is not None:
            if len(styles) > 1:
                out_path = output.with_name(f"{output.stem}_{s}{output.suffix or '.png'}")
            else:
                out_path = output if output.suffix else output.with_suffix(".png")
        else:
            out_path = video_path.parent / f"{video_path.stem}_thumb_{s}.png"

        if out_path.resolve() == video_path.resolve():
            raise RuntimeError(
                f"Output path matches input video — refusing to overwrite {video_path}"
            )

        result = STYLE_FN[s](bg, title, artist, scaled_font)
        _save_image(result, out_path)

        size_kb = out_path.stat().st_size / 1024
        logger.info(f"  {s:<8} → {out_path.name} ({size_kb:.0f} KB)")
        outputs.append(out_path)

    logger.success(f"Generated {len(outputs)} thumbnail(s)")
    return outputs
