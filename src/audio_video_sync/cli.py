"""CLI for audio-video-sync."""

import sys
from pathlib import Path
from typing import Literal, Optional

import typer
from loguru import logger

from . import __version__

# Keep light so --version/--help don't import Pillow/scipy
ThumbnailStyle = Literal["clean", "gradient"]
ALL_STYLES: tuple[ThumbnailStyle, ...] = ("clean", "gradient")

app = typer.Typer(
    name="avsync",
    help="Auto-sync video with separately recorded audio, and generate thumbnails.",
    add_completion=False,
    no_args_is_help=True,
)


def version_callback(value: bool):
    if value:
        print(f"avsync {__version__}")
        raise typer.Exit()


def _setup_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, format="<level>{message}</level>", level="INFO")


@app.callback()
def common(
    version: bool = typer.Option(
        False, "-v", "--version", callback=version_callback, is_eager=True,
        help="Show version and exit.",
    ),
):
    """Auto-sync video with separately recorded audio, and generate thumbnails."""


@app.command()
def sync(
    video: Path = typer.Argument(..., help="Video file (audio will be replaced)"),
    audio: Path = typer.Argument(..., help="Audio file to sync and merge"),
    output: Optional[Path] = typer.Option(
        None, "-o", "--output", help="Output file (default: video_synced.mp4)",
    ),
    offset: Optional[float] = typer.Option(
        None, "--offset", help="Skip detection; use this offset in seconds",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Detect offset and exit without encoding",
    ),
    analyze: float = typer.Option(
        40.0, "--analyze", help="Seconds of audio to analyze for sync detection",
        min=1.0,
    ),
    no_hwaccel: bool = typer.Option(
        False, "--no-hwaccel", help="Disable hardware video encoding",
    ),
):
    """Sync VIDEO with AUDIO and create a new video file."""
    from .ffmpeg import check_ffmpeg, merge
    from .sync import LOW_CONFIDENCE_THRESHOLD, find_offset

    _setup_logging()

    try:
        if not video.exists():
            logger.error(f"Video not found: {video}")
            raise typer.Exit(1)

        if not audio.exists():
            logger.error(f"Audio not found: {audio}")
            raise typer.Exit(1)

        if not check_ffmpeg():
            logger.error("FFmpeg/ffprobe not found. Install: brew install ffmpeg")
            raise typer.Exit(1)

        if output is None:
            output = video.parent / f"{video.stem}_synced.mp4"

        if output.resolve() == video.resolve():
            logger.error("Output path matches input video — choose a different -o path")
            raise typer.Exit(1)

        logger.info(f"Video: {video.name}")
        logger.info(f"Audio: {audio.name}")

        confidence: float | None = None
        method = "manual"
        if offset is None:
            offset, confidence, method = find_offset(video, audio, analyze_duration=analyze)
            logger.info(
                f"Detected offset: {offset:.3f}s ({method}, {confidence:.1f}x confidence)"
            )
            if confidence < LOW_CONFIDENCE_THRESHOLD:
                logger.warning(
                    f"Low confidence ({confidence:.1f}x) — offset may be ambiguous "
                    "(repetitive track) or audio may not match video."
                )
                logger.warning(
                    "Check that video and audio are from the same recording session, "
                    "or pass --offset if you know the sync point."
                )
        else:
            logger.info(f"Using manual offset: {offset:.3f}s ({method})")

        if dry_run:
            logger.info("Dry run — skipping encode")
            return

        merge(video, audio, output, offset, allow_hwaccel=not no_hwaccel)

        logger.info("")
        logger.info(f'Tip: generate a thumbnail with:  avsync thumb "{output}" "Song Title"')
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(1) from e


@app.command()
def thumb(
    video: Path = typer.Argument(..., help="Video file to extract frame from"),
    title: str = typer.Argument(..., help="Title text for the thumbnail"),
    artist: Optional[str] = typer.Argument(None, help="Artist name (optional)"),
    output: Optional[Path] = typer.Option(
        None, "-o", "--output", help="Output file path",
    ),
    time: Optional[float] = typer.Option(
        None, "-t", "--time", help="Frame timestamp in seconds (default: middle)",
    ),
    style: Optional[ThumbnailStyle] = typer.Option(
        None, "-s", "--style", help=f"Style: {', '.join(ALL_STYLES)} (default: all)",
    ),
    font_size: int = typer.Option(72, "--font-size", help="Title font size in px"),
    max_edge: int = typer.Option(
        1280, "--max-edge", help="Max long-edge pixels (default: 1280)",
    ),
    save_frame: bool = typer.Option(
        False, "--save-frame", help="Also save the raw extracted frame",
    ),
    open_after: bool = typer.Option(False, "--open", help="Open result after generation"),
):
    """Generate thumbnail(s) from a video frame with text overlay."""
    from .ffmpeg import check_ffmpeg
    from .thumbnail import create_thumbnail, open_path

    _setup_logging()

    try:
        if not video.exists():
            logger.error(f"Video not found: {video}")
            raise typer.Exit(1)

        if not check_ffmpeg():
            logger.error("FFmpeg/ffprobe not found. Install: brew install ffmpeg")
            raise typer.Exit(1)

        outputs = create_thumbnail(
            video_path=video,
            title=title,
            artist=artist,
            output=output,
            timestamp=time,
            style=style,
            font_size=font_size,
            max_edge=max_edge,
            save_frame=save_frame,
        )

        if open_after:
            for p in outputs:
                open_path(p)
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(1) from e


def run():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    run()
