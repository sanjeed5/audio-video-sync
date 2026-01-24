"""CLI for audio-video-sync."""

import sys
from pathlib import Path
from typing import Optional

import typer
from loguru import logger

from . import __version__
from .sync import find_offset
from .ffmpeg import merge, check_ffmpeg

app = typer.Typer(
    name="avsync",
    help="Auto-sync video with separately recorded audio using cross-correlation.",
    add_completion=False,
)


def version_callback(value: bool):
    if value:
        print(f"avsync {__version__}")
        raise typer.Exit()


@app.command()
def main(
    video: Path = typer.Argument(..., help="Video file (audio will be replaced)"),
    audio: Path = typer.Argument(..., help="Audio file to sync and merge"),
    output: Optional[Path] = typer.Option(
        None, "-o", "--output", help="Output file (default: video_synced.mp4)"
    ),
    version: bool = typer.Option(
        False, "-v", "--version", callback=version_callback, is_eager=True
    ),
):
    """
    Sync VIDEO with AUDIO and create a new video file.
    
    Automatically detects the time offset between the video's original audio
    and the replacement audio using cross-correlation, then merges them.
    """
    # Configure logging
    logger.remove()
    logger.add(sys.stderr, format="<level>{message}</level>", level="INFO")
    
    # Validate inputs
    if not video.exists():
        logger.error(f"Video not found: {video}")
        raise typer.Exit(1)
    
    if not audio.exists():
        logger.error(f"Audio not found: {audio}")
        raise typer.Exit(1)
    
    if not check_ffmpeg():
        logger.error("FFmpeg not found. Install it: brew install ffmpeg")
        raise typer.Exit(1)
    
    # Default output name
    if output is None:
        output = video.parent / f"{video.stem}_synced.mp4"
    
    logger.info(f"Video: {video.name}")
    logger.info(f"Audio: {audio.name}")
    
    # Find offset
    offset, confidence, method = find_offset(video, audio)
    logger.info(f"Detected offset: {offset:.3f}s ({method}, {confidence:.1f}x confidence)")
    
    if confidence < 3:
        logger.warning("Low confidence - sync may be inaccurate")
    
    # Merge
    merge(video, audio, output, offset)


def run():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    run()
