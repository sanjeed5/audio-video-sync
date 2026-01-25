# audio-video-sync

Auto-sync video with separately recorded audio using cross-correlation.

Perfect for music covers where you record video on your phone and audio in a DAW separately.

## Features

- **Auto sync detection** using cross-correlation (waveform + chromagram)
- **Auto trim** output to match replacement audio duration
- **VFR to CFR conversion** prevents sync drift on phone videos
- **Hardware acceleration** on macOS (VideoToolbox) - 4.7x faster
- **Low confidence warning** detects mismatched files

## Installation

```bash
# Requires FFmpeg
brew install ffmpeg  # macOS

# Install from PyPI
pip install audio-video-sync

# Or with uv
uv tool install audio-video-sync
```

## Usage

```bash
# Basic usage - auto-detects sync and creates video_synced.mp4
avsync video.mp4 audio.wav

# Specify output file
avsync video.mp4 audio.wav -o output.mp4
```

Output video will be automatically trimmed to match the replacement audio's duration.

## How It Works

1. **Extract audio** from video using ffmpeg
2. **Cross-correlate** using two methods:
   - **Waveform correlation**: Compares raw audio. Precise when recordings are similar.
   - **Chromagram correlation**: Compares pitch content. Robust to EQ, compression, reverb.
3. **Pick the best method** based on confidence score
4. **Merge & trim** video with synced audio, converting VFR to CFR

## Use Case

You recorded a cover:
- Phone video has your performance + room noise
- DAW export has clean, polished audio

This tool finds the exact offset, syncs them, and outputs a video matching your audio's timing.

## Requirements

- Python 3.10+
- FFmpeg installed and in PATH

## License

MIT
