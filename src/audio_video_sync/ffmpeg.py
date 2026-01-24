"""FFmpeg wrapper for merging video with synced audio."""

import subprocess
from pathlib import Path
from loguru import logger


def merge(video_path: Path, audio_path: Path, output_path: Path, offset: float) -> None:
    """
    Merge video with new audio at the specified offset.
    
    Args:
        video_path: Source video file
        audio_path: Replacement audio file  
        output_path: Output video file
        offset: Time offset in seconds
            - offset > 0: delay the audio (audio starts later)
            - offset < 0: trim audio from start
    """
    logger.info(f"Merging with offset: {offset:.3f}s")
    
    if offset >= 0:
        # Audio starts later - delay it
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-itsoffset", str(offset),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_path)
        ]
    else:
        # Audio starts earlier - trim from start
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", str(abs(offset)),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_path)
        ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg error: {result.stderr}")
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")
    
    logger.success(f"Created: {output_path}")
    logger.info(f"Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")


def check_ffmpeg() -> bool:
    """Check if FFmpeg is installed."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
