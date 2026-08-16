"""FFmpeg wrapper for merging video with synced audio."""

import math
import platform
import re
import subprocess
import sys
from collections import deque
from functools import lru_cache
from pathlib import Path

from loguru import logger


def check_ffmpeg() -> bool:
    """Check if FFmpeg and ffprobe are installed."""
    for binary in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run([binary, "-version"], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
    return True


def get_duration(file_path: Path) -> float:
    """Get duration of audio/video file in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    raw = result.stdout.strip()
    if not raw or raw.upper() == "N/A":
        raise RuntimeError(f"Could not determine duration of {file_path.name}")
    return float(raw)


def get_frame_rate(file_path: Path) -> str:
    """
    Get video frame rate as a reduced num/den string for ffmpeg -r.

    Prefers avg_frame_rate (actual capture rate) over r_frame_rate, which can
    be inflated on VFR phone video.
    """
    for field in ("avg_frame_rate", "r_frame_rate"):
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", f"stream={field}",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            continue
        rate = result.stdout.strip()
        if not rate or rate in ("0/0", "N/A"):
            continue
        try:
            num_s, den_s = rate.split("/")
            num, den = int(num_s), int(den_s)
            value = num / den
        except (ValueError, ZeroDivisionError):
            continue
        # Reject absurd VFR placeholders (e.g. 90000/1), allow slow-mo up to 240fps
        if 1.0 <= value <= 300.0:
            g = math.gcd(num, den)
            return f"{num // g}/{den // g}"
    logger.warning("Could not read a sane frame rate — falling back to 30fps")
    return "30/1"


@lru_cache(maxsize=1)
def get_video_encoder(allow_hwaccel: bool = True) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """
    Get the best available video encoder and its options.

    Returns:
        Tuple of (encoder_name, encoder_options, input_options)
    """
    if allow_hwaccel and platform.system() == "Darwin":
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True,
        )
        if "h264_videotoolbox" in result.stdout:
            logger.info("Using hardware acceleration (VideoToolbox)")
            return (
                "h264_videotoolbox",
                ("-q:v", "80", "-pix_fmt", "yuv420p"),
                ("-hwaccel", "videotoolbox"),
            )

    logger.info("Using software encoder (libx264)")
    return "libx264", ("-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"), ()


def _parse_time(time_str: str) -> float:
    """Parse ffmpeg time string (HH:MM:SS.xx) to seconds."""
    parts = time_str.split(":")
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def _run_ffmpeg_with_progress(cmd: list[str], duration: float) -> None:
    """Run ffmpeg command with live progress; keep stderr tail on failure."""
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    assert proc.stderr is not None
    time_re = re.compile(r"time=(\d+:\d+:\d+\.\d+)")
    is_tty = sys.stderr.isatty()
    stderr_tail: deque[str] = deque(maxlen=40)
    last_pct_logged = -1

    for line in proc.stderr:
        stderr_tail.append(line.rstrip())
        match = time_re.search(line)
        if not match or duration <= 0:
            continue
        current = _parse_time(match.group(1))
        pct = min(current / duration * 100, 100)
        if is_tty:
            bar_len = 30
            filled = int(bar_len * pct / 100)
            bar = "█" * filled + "░" * (bar_len - filled)
            sys.stderr.write(f"\r  Encoding {bar} {pct:.0f}%")
            sys.stderr.flush()
        else:
            # Periodic percentage so non-TTY logs don't look hung
            bucket = int(pct // 10) * 10
            if bucket > last_pct_logged:
                sys.stderr.write(f"  Encoding {bucket}%\n")
                sys.stderr.flush()
                last_pct_logged = bucket

    if is_tty:
        sys.stderr.write("\r" + " " * 50 + "\r")
        sys.stderr.flush()

    proc.wait()
    if proc.returncode != 0:
        detail = "\n".join(line for line in stderr_tail if line) or "(no stderr)"
        raise RuntimeError(f"FFmpeg encoding failed:\n{detail}")


def merge(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    offset: float,
    *,
    allow_hwaccel: bool = True,
) -> None:
    """
    Merge video with new audio at the specified offset.

    Args:
        video_path: Source video file
        audio_path: Replacement audio file
        output_path: Output video file
        offset: Time offset in seconds
            - offset > 0: seek video forward (music starts later in video)
            - offset < 0: trim audio from start
        allow_hwaccel: Use VideoToolbox on macOS when available
    """
    if output_path.resolve() == video_path.resolve():
        raise RuntimeError(
            f"Output path matches input video — refusing to overwrite {video_path}"
        )

    audio_duration = get_duration(audio_path)
    video_duration = get_duration(video_path)
    logger.info(f"New audio duration: {audio_duration:.3f}s")
    logger.info(f"Merging with offset: {offset:.3f}s")

    fps = get_frame_rate(video_path)
    encoder, encoder_opts, input_opts = get_video_encoder(allow_hwaccel)
    # lru_cache with bool arg — convert tuples back for splat
    encoder_opts_list = list(encoder_opts)
    input_opts_list = list(input_opts)

    if offset >= 0:
        needed = offset + audio_duration
        if needed > video_duration + 0.05:
            raise RuntimeError(
                f"Video too short: need {needed:.1f}s from offset {offset:.1f}s "
                f"but video is only {video_duration:.1f}s"
            )
        target_duration = audio_duration
        logger.info(f"Syncing: video from {offset:.3f}s, {fps} CFR")

        # Fast-seek near the cut, then sample-accurate trim.
        # No hwaccel decode here: filter_complex needs software frames.
        # Hardware *encode* (VideoToolbox) still applies via encoder opts.
        seek_pre = max(0.0, offset - 2.0)
        trim_start = offset - seek_pre
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(seek_pre),
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            f"[0:v]trim=start={trim_start},setpts=PTS-STARTPTS[v]",
            "-map", "[v]",
            "-map", "1:a:0",
            "-map_metadata", "0",
            "-fps_mode", "cfr",
            "-r", fps,
            "-c:v", encoder,
            *encoder_opts_list,
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(target_duration),
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        trim_audio = abs(offset)
        if trim_audio >= audio_duration:
            raise RuntimeError(
                f"Offset {-offset:.1f}s exceeds audio duration {audio_duration:.1f}s"
            )
        target_duration = audio_duration - trim_audio
        if target_duration > video_duration + 0.05:
            raise RuntimeError(
                f"Video too short: need {target_duration:.1f}s but video is "
                f"only {video_duration:.1f}s"
            )
        logger.info(f"Trimming audio: skipping first {trim_audio:.3f}s, {fps} CFR")

        # Sample-accurate audio trim (works for mp3/m4a, not just WAV)
        cmd = [
            "ffmpeg", "-y",
            *input_opts_list,
            "-i", str(video_path),
            "-i", str(audio_path),
            "-filter_complex",
            f"[1:a]atrim=start={trim_audio},asetpts=PTS-STARTPTS[a]",
            "-map", "0:v:0",
            "-map", "[a]",
            "-map_metadata", "0",
            "-fps_mode", "cfr",
            "-r", fps,
            "-c:v", encoder,
            *encoder_opts_list,
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(target_duration),
            "-movflags", "+faststart",
            str(output_path),
        ]

    _run_ffmpeg_with_progress(cmd, target_duration)

    logger.success(f"Created: {output_path}")
    logger.info(f"Size: {output_path.stat().st_size / 1024 / 1024:.1f} MB")
