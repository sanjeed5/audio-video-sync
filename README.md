# audio-video-sync

Auto-sync video with separately recorded audio using cross-correlation.

Perfect for music covers where you record video on your phone and audio in a DAW separately.

## Installation

```bash
# Requires FFmpeg
brew install ffmpeg  # macOS

# Install from PyPI
uv pip install audio-video-sync

# Or from source
git clone https://github.com/sanjeed5/audio-video-sync
cd audio-video-sync
uv pip install -e .
```

## Usage

```bash
# Basic usage - auto-detects sync and creates video_synced.mp4
avsync video.mp4 audio.mp3

# Specify output file
avsync video.mp4 audio.mp3 -o output.mp4
```

## How It Works

1. **Extract audio** from both video and replacement audio
2. **Cross-correlate** using two methods:
   - **Chromagram correlation**: Compares pitch content over time. Robust to EQ, compression, reverb differences.
   - **Waveform correlation**: Compares raw audio. More precise when recordings are similar.
3. **Pick the best method** based on confidence score
4. **Merge** video with synced audio using FFmpeg

## Use Case

You recorded a cover:
- Phone video has your singing + room noise + keyboard bleed
- DAW export has clean MIDI + processed vocals

This tool finds the exact offset between them and creates a final video with the polished audio.

## Requirements

- Python 3.10+
- FFmpeg installed and in PATH

## License

MIT
