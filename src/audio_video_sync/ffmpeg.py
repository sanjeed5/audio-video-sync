"""FFmpeg wrapper for merging video with synced audio."""

import platform
import subprocess
from pathlib import Path

from loguru import logger


def get_duration(file_path: Path) -> float:
    """Get duration of audio/video file in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def get_frame_rate(file_path: Path) -> float:
    """Get video frame rate. Returns 30 as fallback."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 30.0
    try:
        # Frame rate is returned as "num/den" (e.g., "30/1")
        num, den = result.stdout.strip().split("/")
        return float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return 30.0


def get_video_encoder() -> tuple[str, list[str]]:
    """
    Get the best available video encoder and its options.
    Uses hardware acceleration on macOS (VideoToolbox) with software fallback.
    
    Returns:
        Tuple of (encoder_name, encoder_options)
    """
    if platform.system() == "Darwin":
        # macOS - try VideoToolbox hardware encoder
        # Check if h264_videotoolbox is available
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True
        )
        if "h264_videotoolbox" in result.stdout:
            logger.info("Using hardware encoder (VideoToolbox)")
            return "h264_videotoolbox", ["-q:v", "65"]  # quality 0-100, 65 ≈ CRF 18
    
    # Fallback to software encoder
    logger.info("Using software encoder (libx264)")
    return "libx264", ["-preset", "fast", "-crf", "18"]


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
    # Get the duration of the new audio - output video will match this length
    audio_duration = get_duration(audio_path)
    logger.info(f"New audio duration: {audio_duration:.3f}s")
    logger.info(f"Merging with offset: {offset:.3f}s")
    
    # Get video frame rate and encoder
    fps = get_frame_rate(video_path)
    encoder, encoder_opts = get_video_encoder()
    
    if offset >= 0:
        # Single-pass: seek video to offset, use audio from start, encode only what we need
        logger.info(f"Syncing: video from {offset:.3f}s, {fps:.0f}fps CFR")
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(offset),           # fast seek to offset (before -i)
            "-i", str(video_path),
            "-i", str(audio_path),        # audio from start
            "-map", "0:v:0",
            "-map", "1:a:0",
            # Convert VFR to CFR to prevent sync drift
            "-fps_mode", "cfr",
            "-r", str(int(round(fps))),
            "-c:v", encoder,
            *encoder_opts,
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(audio_duration),    # output duration = audio length
            "-movflags", "+faststart",
            str(output_path)
        ]
        
    else:
        # Audio has intro before performance - trim audio start
        trim_audio = abs(offset)
        effective_duration = audio_duration - trim_audio
        logger.info(f"Trimming audio: skipping first {trim_audio:.3f}s, {fps:.0f}fps CFR")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", str(trim_audio),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-fps_mode", "cfr",
            "-r", str(int(round(fps))),
            "-c:v", encoder,
            *encoder_opts,
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(effective_duration),
            "-movflags", "+faststart",
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
