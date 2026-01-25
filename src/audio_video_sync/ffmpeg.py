"""FFmpeg wrapper for merging video with synced audio."""

import os
import subprocess
import tempfile
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
    
    if offset >= 0:
        # Two-step approach:
        # Step 1: Sync audio with -itsoffset + convert VFR to CFR (fixes drift)
        # Step 2: Trim to audio duration
        
        logger.info(f"Step 1: Syncing audio (delay {offset:.3f}s) + converting VFR to CFR")
        
        # Create temp file for intermediate synced video
        temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4')
        os.close(temp_fd)
        
        try:
            # Step 1: Sync with CFR conversion to fix drift
            sync_cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-itsoffset", str(offset),    # delay audio to match video timing
                "-i", str(audio_path),
                "-map", "0:v:0",
                "-map", "1:a:0",
                # Convert VFR to CFR to prevent sync drift
                "-fps_mode", "cfr",
                "-r", "30",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "192k",
                temp_path
            ]
            
            result = subprocess.run(sync_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Sync step failed: {result.stderr}")
            
            logger.info(f"Step 2: Trimming to audio duration ({audio_duration:.3f}s)")
            
            # Step 2: Trim - cut from offset for audio_duration
            # Now we can use -c copy since video is already CFR
            trim_cmd = [
                "ffmpeg", "-y",
                "-ss", str(offset),
                "-i", temp_path,
                "-t", str(audio_duration),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path)
            ]
            
            result = subprocess.run(trim_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Trim step failed: {result.stderr}")
                
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
        logger.success(f"Created: {output_path}")
        logger.info(f"Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
        return
        
    else:
        # Audio has intro before performance - trim audio start
        # Use single-pass with CFR conversion
        trim_audio = abs(offset)
        effective_duration = audio_duration - trim_audio
        logger.info(f"Trimming audio: skipping first {trim_audio:.3f}s, duration {effective_duration:.3f}s")
        logger.info("Converting VFR to CFR (30fps) to prevent sync drift...")
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-ss", str(trim_audio),
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-fps_mode", "cfr",
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
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
