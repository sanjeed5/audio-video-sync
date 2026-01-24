"""
Core audio synchronization using cross-correlation.

Uses both chromagram (pitch-based) and raw waveform correlation,
automatically selecting the method with higher confidence.
"""

import numpy as np
from scipy import signal
from pathlib import Path
from loguru import logger
import librosa

# Analysis parameters
ANALYZE_DURATION = 40  # seconds to analyze
ANALYSIS_SR = 22050  # sample rate for analysis
HOP_LENGTH = 512  # hop length for chroma computation


def find_offset(video_path: Path, audio_path: Path) -> tuple[float, float, str]:
    """
    Find the time offset between video's audio and the replacement audio.
    
    Uses both chromagram correlation (robust to processing) and raw waveform
    correlation (precise when similar), automatically picking the better method.
    
    Args:
        video_path: Path to video file (audio will be extracted)
        audio_path: Path to replacement audio file
        
    Returns:
        Tuple of (offset_seconds, confidence, method_used)
        - offset > 0 means replacement audio should be delayed
        - offset < 0 means replacement audio should be trimmed from start
    """
    logger.info("Loading audio from video...")
    scratch, sr = librosa.load(video_path, sr=ANALYSIS_SR, duration=ANALYZE_DURATION, mono=True)
    
    logger.info("Loading replacement audio...")
    mastered, _ = librosa.load(audio_path, sr=ANALYSIS_SR, duration=ANALYZE_DURATION, mono=True)
    
    logger.info(f"Analyzing {len(scratch)/sr:.1f}s of audio")
    
    # Method 1: Chromagram correlation (robust to EQ, compression, reverb)
    chroma_offset, chroma_conf = _correlate_chroma(scratch, mastered, sr)
    logger.info(f"Chromagram: {chroma_offset:.3f}s (confidence: {chroma_conf:.1f}x)")
    
    # Method 2: Raw waveform correlation (precise when audio is similar)
    raw_offset, raw_conf = _correlate_raw(scratch, mastered, sr)
    logger.info(f"Waveform:   {raw_offset:.3f}s (confidence: {raw_conf:.1f}x)")
    
    # Pick the method with higher confidence (prefer raw if close, it's more precise)
    if raw_conf > chroma_conf * 0.8:
        logger.info("Using waveform correlation (higher precision)")
        return raw_offset, raw_conf, "waveform"
    else:
        logger.info("Using chromagram correlation (more robust)")
        return chroma_offset, chroma_conf, "chromagram"


def _correlate_chroma(audio1: np.ndarray, audio2: np.ndarray, sr: int) -> tuple[float, float]:
    """Correlate using chromagram (pitch content over time)."""
    chroma1 = librosa.feature.chroma_cqt(y=audio1, sr=sr, hop_length=HOP_LENGTH)
    chroma2 = librosa.feature.chroma_cqt(y=audio2, sr=sr, hop_length=HOP_LENGTH)
    
    # Sum across pitch classes to get energy over time
    energy1 = np.sum(chroma1, axis=0)
    energy2 = np.sum(chroma2, axis=0)
    
    correlation = signal.correlate(energy1, energy2, mode='full')
    peak_idx = np.argmax(correlation)
    
    zero_lag_idx = len(energy2) - 1
    lag_frames = peak_idx - zero_lag_idx
    offset = (lag_frames * HOP_LENGTH) / sr
    
    confidence = correlation[peak_idx] / np.mean(np.abs(correlation))
    return offset, confidence


def _correlate_raw(audio1: np.ndarray, audio2: np.ndarray, sr: int) -> tuple[float, float]:
    """Correlate raw waveforms directly."""
    correlation = signal.correlate(audio1, audio2, mode='full')
    peak_idx = np.argmax(np.abs(correlation))
    
    zero_lag_idx = len(audio2) - 1
    lag_samples = peak_idx - zero_lag_idx
    offset = lag_samples / sr
    
    confidence = np.abs(correlation[peak_idx]) / np.mean(np.abs(correlation))
    return offset, confidence
