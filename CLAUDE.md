# WireClaw — Pi Zero 2W

## Hardware
- Modèle : Raspberry Pi Zero 2W
- CPU : 4× ARM Cortex-A53 @1GHz
- GPU : VideoCore IV — encodeur H264 hardware disponible via v4l2h264enc (/dev/video11)
- RAM : 512MB
- OS : Raspberry Pi OS Bookworm Lite (64-bit)
- Caméra : OV5647 (module CSI standard Raspberry Pi)
- Boîtier : dissipateur thermique
- Charge CPU encodage : ~40% CPU (hw) vs ~80-90% (sw x264)
- Prérequis : gpu_mem=160 dans /boot/firmware/config.txt

## Stack
- Caméra : libcamerasrc OBLIGATOIRE (Bookworm, pas v4l2src)
- Encodage : v4l2h264enc hardware (défaut) → x264enc software (fallback auto)
- omxh264enc : non disponible sur Bookworm 64-bit (OpenMAX supprimé)
- Transport : RTP H264 pt=96 UDP
- Flask : API légère port 5000 (health + settings uniquement, pas de MJPEG local)
- h264parse requis : `sudo apt install gstreamer1.0-plugins-bad -y`

## Réseau
- Dev Freebox : 192.168.1.132 → Jetson 192.168.1.84:5600
- Hotspot WireClaw : DHCP → Jetson 10.42.0.1:5600

## Pipelines validés

### Hardware (v4l2h264enc) — défaut
gst-launch-1.0 libcamerasrc ! \
  video/x-raw,width=1280,height=720,format=NV12,framerate=15/1 ! \
  v4l2convert ! \
  v4l2h264enc ! \
  video/x-h264,level=(string)3.2 ! \
  h264parse ! \
  rtph264pay config-interval=1 pt=96 ! queue ! \
  udpsink host=192.168.1.84 port=5600

### Software (x264enc) — fallback
gst-launch-1.0 libcamerasrc ! \
  video/x-raw,width=640,height=480,framerate=15/1 ! \
  videoconvert ! x264enc tune=zerolatency bitrate=1000 ! \
  rtph264pay config-interval=1 pt=96 ! \
  udpsink host=192.168.1.84 port=5600

## Rôle dans WireClaw
- Émet uniquement le flux RTP vers le Jetson
- Pas de traitement local (YOLOv8 tourne sur le Jetson CUDA)
- Réglages caméra via POST /settings (proxyfié depuis FastAPI Jetson)

## Installation
```bash
git clone https://git.syoul.fr/nicoboy/wireclaw-pizero
cd wireclaw-pizero
bash install.sh
cp .env.dev .env
python3 camera_server.py
```

## Repo
git.syoul.fr/nicoboy/wireclaw-pizero

Après clone : `bash install.sh`
 ## Mise à jour du code sur le Pi Zero

Le Pi Zero n'est joignable que depuis le Jetson (hotspot WireClaw,
10.42.0.0/24). Après un commit/push sur ce repo (fait depuis le PC
ou l'interface web Gitea), synchroniser le Pi Zero avec :

    ssh jetson-pi "cd ~/wireclaw-pizero && git pull"

Puis redémarrer le service concerné, par exemple :

    ssh jetson-pi "sudo systemctl restart wireclaw-cam.service"