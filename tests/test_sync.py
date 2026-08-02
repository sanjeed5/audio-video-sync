"""Tests for sync detection and helpers."""

import numpy as np
import pytest

from audio_video_sync.ffmpeg import _parse_time
from audio_video_sync.sync import (
    ANALYSIS_SR,
    LOW_CONFIDENCE_THRESHOLD,
    _correlate_chroma,
    _correlate_raw,
    _peak_ratio_confidence,
)


def _unique_signal(duration: float, sr: int = ANALYSIS_SR, seed: int = 1) -> np.ndarray:
    """Broadband signal with weak self-similarity (sharp correlation peak)."""
    rng = np.random.default_rng(seed)
    n = int(duration * sr)
    # White noise → near-delta autocorrelation
    noise = rng.standard_normal(n).astype(np.float64)
    t = np.arange(n) / sr
    bursts = np.zeros(n, dtype=np.float64)
    for start, freq, decay in ((0.2, 220, 6), (2.0, 330, 5), (4.5, 440, 4)):
        env = np.exp(-decay * (t - start))
        env[t < start] = 0
        bursts += env * np.sin(2 * np.pi * freq * t)
    return (0.7 * noise + 0.3 * bursts).astype(np.float32)


def _shifted_pair(offset_s: float, duration: float = 8.0):
    """Build scratch/mastered pair where mastered starts `offset_s` into scratch."""
    sr = ANALYSIS_SR
    base = _unique_signal(duration, sr)
    pad = int(abs(offset_s) * sr)
    if offset_s >= 0:
        scratch = np.concatenate([np.zeros(pad, dtype=np.float32), base])
        mastered = base.copy()
    else:
        scratch = base.copy()
        mastered = np.concatenate([np.zeros(pad, dtype=np.float32), base])
    return scratch, mastered, sr


@pytest.mark.parametrize("offset_s", [0.0, 0.5, 1.25, 3.0])
def test_correlate_raw_recovers_positive_offset(offset_s: float):
    scratch, mastered, sr = _shifted_pair(offset_s)
    detected, conf = _correlate_raw(scratch, mastered, sr)
    assert conf > LOW_CONFIDENCE_THRESHOLD
    assert detected == pytest.approx(offset_s, abs=0.05)


@pytest.mark.parametrize("offset_s", [-0.5, -1.0])
def test_correlate_raw_recovers_negative_offset(offset_s: float):
    scratch, mastered, sr = _shifted_pair(offset_s)
    detected, conf = _correlate_raw(scratch, mastered, sr)
    assert conf > LOW_CONFIDENCE_THRESHOLD
    assert detected == pytest.approx(offset_s, abs=0.05)


def test_correlate_chroma_recovers_offset():
    scratch, mastered, sr = _shifted_pair(2.0, duration=10.0)
    detected, conf = _correlate_chroma(scratch, mastered, sr)
    assert conf > LOW_CONFIDENCE_THRESHOLD
    assert detected == pytest.approx(2.0, abs=0.1)


def test_unrelated_audio_has_low_confidence():
    """Mismatched signals should not clear the low-confidence threshold."""
    a = _unique_signal(6.0, seed=1)
    b = _unique_signal(6.0, seed=99)
    _, conf = _correlate_raw(a, b, ANALYSIS_SR)
    assert conf < LOW_CONFIDENCE_THRESHOLD


def test_peak_ratio_confidence():
    corr = np.zeros(100)
    corr[40] = 10.0
    corr[80] = 2.0
    assert _peak_ratio_confidence(corr, 40, guard=5) == pytest.approx(5.0)


def test_parse_time():
    assert _parse_time("00:00:01.50") == pytest.approx(1.5)
    assert _parse_time("01:02:03.00") == pytest.approx(3723.0)


def test_edge_reject_uses_direction_specific_limit():
    """Short audio + long video lead-in must not reject a correct positive offset."""
    scratch, mastered, sr = _shifted_pair(5.0, duration=6.0)
    # mastered is 6s; scratch is 11s — positive offset 5s is valid (< 0.9 * 11)
    detected, conf = _correlate_raw(scratch, mastered, sr)
    assert detected == pytest.approx(5.0, abs=0.05)
    assert conf > LOW_CONFIDENCE_THRESHOLD
    max_pos = len(scratch) / sr
    assert abs(detected) < max_pos * 0.9
