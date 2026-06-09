# WireClaw — Pi Zero 2W

## Contexte
Composant vidéo du drone d'inspection WireClaw.
Caméra OV5647 (CSI) → GStreamer RTP H264 → Jetson

## Stack
- OS : Raspberry Pi OS Bookworm Lite
- Caméra : OV5647, libcamerasrc (pas v4l2src)
- Encodage : x264enc tune=zerolatency bitrate=1000
- Transport : RTP H264 pt=96 UDP port 5600

## Réseau
- Dev Freebox : Pi Zero 192.168.1.132 → Jetson 192.168.1.84
- Hotspot WireClaw : Pi Zero DHCP → Jetson 10.42.0.1

## Pipeline émetteur validé
gst-launch-1.0 libcamerasrc ! \
  video/x-raw,width=640,height=480,framerate=15/1 ! \
  videoconvert ! x264enc tune=zerolatency bitrate=1000 ! \
  rtph264pay config-interval=1 pt=96 ! \
  udpsink host=192.168.1.84 port=5600

## Repo
git.syoul.fr/nicoboy/wireclaw-pizero