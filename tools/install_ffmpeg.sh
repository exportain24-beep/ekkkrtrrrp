#!/usr/bin/env bash
# ffmpeg from the official Ubuntu archive, with timeouts and retries.
# 11 Nov 2026: a plain `apt-get update` hung for 20+ minutes and cancelled two builds.
set -u
if command -v ffmpeg >/dev/null 2>&1; then ffmpeg -version | head -1; exit 0; fi
OPTS="-o Acquire::Retries=3 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 -o DPkg::Lock::Timeout=60"
for i in 1 2 3; do
  # skip slow third-party lists (only the Ubuntu archive is needed for ffmpeg)
  sudo rm -f /etc/apt/sources.list.d/microsoft-prod.list /etc/apt/sources.list.d/*azure* 2>/dev/null || true
  if timeout 180 sudo apt-get update -qq $OPTS && timeout 300 sudo apt-get install -y -qq --no-install-recommends $OPTS ffmpeg > /dev/null; then
    ffmpeg -version | head -1; exit 0
  fi
  echo "apt attempt $i failed – retrying"; sleep 10
done
exit 1
