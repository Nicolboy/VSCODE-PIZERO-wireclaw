#!/bin/bash
set -e

sudo apt update
sudo apt install -y \
  python3-flask \
  python3-opencv \
  python3-dotenv \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libcamera \
  gstreamer1.0-x \
  gstreamer1.0-gl \
  libcamera-apps \
  rpicam-apps \
  v4l-utils

# GPU memory pour v4l2h264enc hardware encoder
if ! grep -q "gpu_mem=160" /boot/firmware/config.txt; then
  echo "gpu_mem=160" | sudo tee -a /boot/firmware/config.txt
  echo "⚠️  Reboot requis pour activer gpu_mem=160"
fi

echo "✅ Installation terminée"
