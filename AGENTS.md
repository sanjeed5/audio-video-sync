# Agent Guidelines for audio-video-sync

## Project Overview

CLI tool to auto-sync video with separately recorded audio using cross-correlation. Designed for music covers where video is recorded on phone and audio in a DAW.

## Key Files

- `src/audio_video_sync/cli.py` - CLI entry point (typer, subcommands: `sync` and `thumb`)
- `src/audio_video_sync/sync.py` - Audio analysis and correlation
- `src/audio_video_sync/ffmpeg.py` - Video merging with ffmpeg
- `src/audio_video_sync/thumbnail.py` - Thumbnail generation (frame extraction + Pillow text overlay)

## Technical Details

- Uses cross-correlation (waveform + chromagram) to find offset
- Confidence is peak / secondary-peak (length-invariant); warn below `LOW_CONFIDENCE_THRESHOLD`
- Converts VFR to CFR to prevent sync drift
- Hardware acceleration on macOS (VideoToolbox) for encode at `-q:v 80` (~8 Mbps 1080p, Instagram+YouTube). Do not drop back to 65 (lands ~2.4 Mbps). Positive-offset path skips hw *decode* because `filter_complex` needs software frames
- Output is trimmed to match replacement audio duration
- Sample-accurate cuts: video `trim` (+ optional pre-seek), audio `atrim`

## CLI import rule

**Never** eagerly import `sync` / `thumbnail` (scipy, librosa, Pillow) at module top in `cli.py`. Lazy-import inside commands so `avsync --version` / `--help` stay instant.

## Version Management

**IMPORTANT**: Version is defined in ONE place:
- `src/audio_video_sync/__init__.py` (`__version__`)

`pyproject.toml` reads it via hatch dynamic version (`[tool.hatch.version]`).

## Publishing to PyPI

When making changes that affect functionality, bump version, test, and publish to PyPI in the same turn. Git commit and push still wait for an explicit ask.

Publish steps:

1. Bump version in `src/audio_video_sync/__init__.py`
2. Update `README.md` if features changed
3. Run `uv run pytest`
4. Build and publish:

```bash
rm -rf dist/
uv build
uv run twine upload dist/*
```

5. Refresh the local tool install so PATH matches PyPI: `uv tool install --force .`

## Testing

```bash
uv run pytest
uv run avsync sync video.mp4 audio.wav --dry-run
uv run avsync thumb video.mp4 "Song Title" "Artist"
```

Check output for:
- Correct sync (audio matches video)
- No drift over time
- Correct duration (matches audio file)
- Progress bar renders during encode (interactive terminal only)
- Low-confidence warning can fire on highly repetitive/looped tracks even when offset is correct
