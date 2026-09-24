#!/usr/bin/env bash
# Reconstruit la vidéo finale : ./build.sh <video_source.mp4> <dossier_travail>
set -euo pipefail
SRC="$1"; WORK="$2"; HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$WORK/r3d" "$HERE/output"
python3 "$HERE/src/sfx.py" "$WORK/sfx" 38
for n in houses play question suitcase coins cursor gift gears shield rocket; do
  python3 "$HERE/src/render3d.py" "$n" "$WORK/r3d/$n" 12
done
ffmpeg -v error -y -i "$SRC" -vn -ac 2 -ar 44100 -af "highpass=f=85,lowpass=f=15000,equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1.2:g=3,equalizer=f=9000:t=q:w=1:g=2,acompressor=threshold=-20dB:ratio=3:attack=5:release=80:makeup=2" "$WORK/voice.wav"
python3 "$HERE/src/audio.py" "$WORK/voice.wav" "$WORK/sfx" "$WORK/mix.wav"
python3 "$HERE/src/composite.py" "$SRC" "$WORK/r3d" | ffmpeg -v error -y \
  -f rawvideo -pix_fmt bgr24 -s 1080x1920 -r 30 -i - -i "$WORK/mix.wav" \
  -c:v libx264 -preset slow -b:v 5000k -maxrate 6M -bufsize 12M -pix_fmt yuv420p -profile:v high \
  -af "loudnorm=I=-14:TP=-1.0:LRA=9" -c:a aac -b:a 192k -ar 48000 -movflags +faststart -shortest \
  "$HERE/output/montage_final.mp4"
echo "OK -> output/montage_final.mp4"
