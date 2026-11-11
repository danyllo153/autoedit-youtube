#!/usr/bin/env bash
# Gera material de teste sintético (sem precisar de gameplay real):
#   test_footage/gameplay_test.mp4  (~3,6 min, cortes duros, áudio variando)
#   test_footage/music/track.mp3    (música de teste)
#   test_footage/photos/p{1,2,3}.jpg (fotos paisagem e retrato)
set -euo pipefail
mkdir -p test_footage/music test_footage/photos && cd test_footage
i=0
for spec in "testsrc2=s=1280x720:r=30|0.02" "mandelbrot=s=1280x720:r=30|0.4" \
            "life=s=1280x720:r=30:mold=10:ratio=0.1:death_color=#C83232|0.05" \
            "smptebars=s=1280x720:r=30|0.01" "testsrc=s=1280x720:r=30|0.6" \
            "rgbtestsrc=s=1280x720:r=30|0.1"; do
  src=${spec%%|*}; vol=${spec##*|}
  for rep in 1 2; do
    i=$((i+1)); dur=$((10 + (i*7)%15))
    ffmpeg -y -v error -f lavfi -i "$src" -f lavfi -i "sine=frequency=$((200+i*60)):sample_rate=44100" \
      -t $dur -af "volume=$vol" -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac seg$i.mp4
  done
done
for f in $(ls seg*.mp4 | sort -V); do echo "file '$f'"; done > l.txt
ffmpeg -y -v error -f concat -safe 0 -i l.txt -c copy gameplay_test.mp4
rm -f seg*.mp4 l.txt
ffmpeg -y -v error -f lavfi -i "sine=frequency=330:duration=30,volume=0.5" \
  -f lavfi -i "sine=frequency=440:duration=30" -filter_complex amix=inputs=2 music/track.mp3
for n in 1 2 3; do
  size=1600x1200; [ $n = 2 ] && size=900x1600
  ffmpeg -y -v error -f lavfi -i "testsrc2=s=$size:d=1" -frames:v 1 photos/p$n.jpg
done
echo "Pronto: test_footage/"
