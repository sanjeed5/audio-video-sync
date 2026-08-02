"""
Core audio synchronization using cross-correlation.

Uses both chromagram (pitch-based) and raw waveform correlation with
a length-invariant confidence metric (peak / secondary peak).
"""

import subprocess
from pathlib import Path

import librosa
import numpy as np
from loguru import logger
from scipy import signal

# Analysis parameters
DEFAULT_ANALYZE_DURATION = 40  # seconds to analyze
ANALYSIS_SR = 22050  # sample rate for analysis
HOP_LENGTH = 512  # hop length for chroma computation

# Confidence = primary_peak / secondary_peak (outside a small guard band).
# Unrelated audio typically lands near ~1–1.5; clear matches are >> 2.
LOW_CONFIDENCE_THRESHOLD = 2.0


def _extract_audio_ffmpeg(file_path: Path, duration: float, sr: int) -> np.ndarray:
    """
    Extract audio from video/audio file using ffmpeg.
    Returns mono float32 audio as a writable numpy array.
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(file_path),
        "-t", str(duration),
        "-ac", "1",
        "-ar", str(sr),
        "-f", "f32le",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr.decode()}")

    raw = result.stdout
    if len(raw) < 4:
        raise RuntimeError(f"No audio extracted from {file_path.name}")
    if len(raw) % 4 != 0:
        raw = raw[: len(raw) - (len(raw) % 4)]

    return np.frombuffer(raw, dtype=np.float32).copy()


def _peak_ratio_confidence(correlation: np.ndarray, peak_idx: int, guard: int) -> float:
    """
    Length-invariant confidence: primary peak / best secondary peak.

    Secondary peak is the max |corr| outside ±guard samples of the primary peak.
    """
    peak = float(np.abs(correlation[peak_idx]))
    if peak < 1e-12:
        return 0.0

    mask = np.ones(len(correlation), dtype=bool)
    lo = max(0, peak_idx - guard)
    hi = min(len(correlation), peak_idx + guard + 1)
    mask[lo:hi] = False
    if not np.any(mask):
        return float("inf")

    secondary = float(np.max(np.abs(correlation[mask])))
    if secondary < 1e-12:
        return float("inf")
    return peak / secondary


def find_offset(
    video_path: Path,
    audio_path: Path,
    analyze_duration: float = DEFAULT_ANALYZE_DURATION,
) -> tuple[float, float, str]:
    """
    Find the time offset between video's audio and the replacement audio.

    Uses chromagram correlation (robust to EQ/compression) and raw waveform
    correlation (precise when similar), picking the higher peak-ratio confidence.

    Returns:
        Tuple of (offset_seconds, confidence, method_used)
        - offset > 0: music starts later in the video — seek video forward
        - offset < 0: music starts later in the replacement — trim audio from start
    """
    if analyze_duration <= 0:
        raise RuntimeError("--analyze must be a positive number of seconds")

    logger.info("Extracting audio from video...")
    scratch = _extract_audio_ffmpeg(video_path, analyze_duration, ANALYSIS_SR)

    logger.info("Loading replacement audio...")
    mastered = _extract_audio_ffmpeg(audio_path, analyze_duration, ANALYSIS_SR)

    if len(scratch) < ANALYSIS_SR or len(mastered) < ANALYSIS_SR:
        raise RuntimeError(
            "Need at least 1s of audio in both files for sync detection"
        )

    actual_duration = min(len(scratch), len(mastered)) / ANALYSIS_SR
    logger.info(f"Analyzing {actual_duration:.1f}s of audio")

    chroma_offset, chroma_conf = _correlate_chroma(scratch, mastered, ANALYSIS_SR)
    logger.info(f"Chromagram: {chroma_offset:.3f}s (confidence: {chroma_conf:.1f}x)")

    raw_offset, raw_conf = _correlate_raw(scratch, mastered, ANALYSIS_SR)
    logger.info(f"Waveform:   {raw_offset:.3f}s (confidence: {raw_conf:.1f}x)")

    # Prefer waveform when close — higher time precision
    if raw_conf >= chroma_conf * 0.8:
        offset, confidence, method = raw_offset, raw_conf, "waveform"
        logger.info("Using waveform correlation (higher precision)")
    else:
        offset, confidence, method = chroma_offset, chroma_conf, "chromagram"
        logger.info("Using chromagram correlation (more robust)")

    # Disagreement between methods is a strong mismatch signal
    if abs(raw_offset - chroma_offset) > 0.2:
        logger.warning(
            f"Methods disagree by {abs(raw_offset - chroma_offset):.3f}s "
            f"(waveform {raw_offset:.3f}s vs chromagram {chroma_offset:.3f}s)"
        )

    # Peak pinned near the edge of searchable lag → true offset may exceed window.
    # Positive lag is limited by video (scratch) length; negative by audio length.
    max_pos = len(scratch) / ANALYSIS_SR
    max_neg = len(mastered) / ANALYSIS_SR
    limit = max_pos if offset >= 0 else max_neg
    if abs(offset) >= limit * 0.9:
        raise RuntimeError(
            f"Detected offset {offset:.3f}s is near the searchable limit "
            f"({limit:.1f}s). It may be wrong or truncated — try a larger "
            f"--analyze, or pass --offset if you know the sync point."
        )

    return offset, confidence, method


def _correlate_chroma(audio1: np.ndarray, audio2: np.ndarray, sr: int) -> tuple[float, float]:
    """Correlate chromagrams band-by-band (preserves pitch information)."""
    chroma1 = librosa.feature.chroma_cqt(
        y=audio1, sr=sr, hop_length=HOP_LENGTH, norm=None,
    )
    chroma2 = librosa.feature.chroma_cqt(
        y=audio2, sr=sr, hop_length=HOP_LENGTH, norm=None,
    )

    n_bands = min(chroma1.shape[0], chroma2.shape[0])
    correlation = None
    for i in range(n_bands):
        a = chroma1[i].astype(np.float64)
        b = chroma2[i].astype(np.float64)
        a = a - np.mean(a)
        b = b - np.mean(b)
        c = signal.correlate(a, b, mode="full")
        correlation = c if correlation is None else correlation + c

    assert correlation is not None
    peak_idx = int(np.argmax(correlation))
    zero_lag_idx = chroma2.shape[1] - 1
    lag_frames = peak_idx - zero_lag_idx
    offset = (lag_frames * HOP_LENGTH) / sr
    # Guard ~0.5s in chroma frames
    guard = max(1, int(0.5 * sr / HOP_LENGTH))
    confidence = _peak_ratio_confidence(correlation, peak_idx, guard)
    return offset, confidence


def _correlate_raw(audio1: np.ndarray, audio2: np.ndarray, sr: int) -> tuple[float, float]:
    """Correlate zero-mean raw waveforms."""
    a = audio1.astype(np.float64)
    b = audio2.astype(np.float64)
    a = a - np.mean(a)
    b = b - np.mean(b)

    correlation = signal.correlate(a, b, mode="full")
    peak_idx = int(np.argmax(np.abs(correlation)))

    zero_lag_idx = len(b) - 1
    lag_samples = peak_idx - zero_lag_idx
    offset = lag_samples / sr
    # Guard ~250ms so the main lobe isn't treated as a secondary peak
    guard = max(1, int(0.25 * sr))
    confidence = _peak_ratio_confidence(correlation, peak_idx, guard)
    return offset, confidence
