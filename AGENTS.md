# Agent Guidelines for audio-video-sync

## Project Overview

CLI tool to auto-sync video with separately recorded audio using cross-correlation. Designed for music covers where video is recorded on phone and audio in a DAW.

## Key Files

- `src/audio_video_sync/cli.py` - CLI entry point (typer)
- `src/audio_video_sync/sync.py` - Audio analysis and correlation
- `src/audio_video_sync/ffmpeg.py` - Video merging with ffmpeg

## Technical Details

- Uses cross-correlation (waveform + chromagram) to find offset
- Converts VFR to CFR to prevent sync drift
- Hardware acceleration on macOS (VideoToolbox)
- Output is trimmed to match replacement audio duration

## Publishing to PyPI

**IMPORTANT**: When making changes that affect functionality, update version and publish:

1. Bump version in `pyproject.toml`
2. Update `README.md` if features changed
3. Build and publish:

```bash
# Build
uv build

# Publish (requires TWINE_USERNAME and TWINE_PASSWORD or ~/.pypirc)
uv run twine upload dist/*
```

## Testing

```bash
avsync video.mp4 audio.wav
```

Check output for:
- Correct sync (audio matches video)
- No drift over time
- Correct duration (matches audio file)
