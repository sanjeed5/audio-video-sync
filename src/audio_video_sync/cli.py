"""CLI for audio-video-sync."""

import sys
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from . import __version__

# Keep light so --version/--help don't import scipy/librosa
app = typer.Typer(
    name="avsync",
    help="Auto-sync video with separately recorded audio.",
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
    """Auto-sync video with separately recorded audio."""


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
