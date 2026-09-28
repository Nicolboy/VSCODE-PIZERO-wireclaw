# wireclaw-pizero — émission caméra du drone

Serveur caméra pour le Raspberry Pi Zero 2W embarqué sur le drone WireClaw :
capture la caméra OV5647, encode en H.264 et l'envoie en RTP/UDP vers la
station sol (Jetson Orin Nano), via un lien radio wifibroadcast (WFB-NG)
longue portée.

Côté réception (Jetson, décodage GStreamer + inférence YOLOv8 + MJPEG
annoté) : dépôt `wireclaw-jetson`.

## Ce que fait `camera_server.py`

- API Flask (port 5000) : `/health`, `/settings` (lecture/réglage résolution,
  fps, bitrate, encodeur à chaud).
- Flux vidéo : sous-processus GStreamer, encodeur matériel `v4l2h264enc` par
  défaut, avec repli automatique sur `x264enc` (logiciel) si le matériel
  n'est pas disponible.
- Canal secondaire (« sideband ») : statistiques JSON (résolution, fps,
  température, charge CPU) envoyées 1 fois/seconde en UDP sur le port 5602,
  via le tunnel WFB-NG — pas sur le hotspot WiFi courte portée du drone.

## Configuration

`.env` est la config de base (jamais versionnée). Deux profils versionnés
sont fournis :

- `.env.dev` — appliqué automatiquement par-dessus `.env` s'il est présent
  (résolutions de test documentées en commentaire, y compris leur coût CPU
  mesuré sur ce Pi Zero).
- `.env.prod` — profil de déploiement (bitrate réduit, encodeur auto) ; à
  copier explicitement vers `.env` pour l'utiliser (`cp .env.prod .env`),
  il n'est pas chargé automatiquement.

## Lien radio

`config/wifibroadcast_drone_5ghz.cfg` et `wifibroadcast_drone_24ghz.cfg` :
profils WFB-NG côté drone (canal, `mcs_index`, largeur de bande, timeout
FEC). Le profil 2,4 GHz est un profil de diagnostic/comparaison — sujet à
interférences domestiques sévères en usage réel, voir le dépôt
`wireclaw-jetson` pour le détail. Les réglages `fec_timeout` ont fait
l'objet d'un travail de tuning actif contre des gels périodiques du flux
1080p30 ; l'historique de commits de `config/` documente les valeurs
essayées et pourquoi.

## Installer

```bash
./install.sh   # dépendances système (GStreamer, libcamera, Flask, OpenCV)
                # + configure gpu_mem=160 pour l'encodeur matériel (reboot requis)
cp .env.prod .env   # ou construire son propre .env
python3 camera_server.py
```

## État réel

Le dernier travail versionné porte sur la stabilité du flux 1080p30 (gels
périodiques, ajustement du timeout FEC) — pas un point figé et validé à
100 %, un réglage en cours d'affinage. La réception côté Jetson a été
testée avec succès avec le Pi Zero connecté ; voir `wireclaw-jetson` pour
l'état de bout en bout de la liaison vidéo.

## Licence

[MIT](LICENSE).
