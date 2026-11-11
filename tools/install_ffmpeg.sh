#!/usr/bin/env bash
# ffmpeg for the GitHub runner.
# 11 Nov 2026: the Ubuntu apt archive was unreachable for 30+ minutes and cancelled three builds.
# Order: already installed → Ubuntu archive (one timed attempt) → PyPI package imageio-ffmpeg (static build with x264).
set -u
if command -v ffmpeg >/dev/null 2>&1; then ffmpeg -version | head -1; exit 0; fi
OPTS="-o Acquire::Retries=2 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15 -o DPkg::Lock::Timeout=60"
if timeout 120 sudo apt-get update -qq $OPTS && timeout 180 sudo apt-get install -y -qq --no-install-recommends $OPTS ffmpeg > /dev/null; then
  ffmpeg -version | head -1; exit 0
fi
echo "apt unavailable – using ffmpeg from PyPI (imageio-ffmpeg)"
python -m pip install -q "imageio-ffmpeg>=0.5" || exit 1
FF=$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())") || exit 1
sudo ln -sf "$FF" /usr/local/bin/ffmpeg
ffmpeg -version | head -1
