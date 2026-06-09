#!/usr/bin/env python3
"""
WireClaw — Pi Zero 2W camera server
- MJPEG local stream on port 5000 (Flask)
- RTP H264 stream to Jetson 192.168.1.84:5600 (GStreamer thread)
"""

import subprocess
import threading
import time
import logging

import cv2
from flask import Flask, Response

# --- Configuration -----------------------------------------------------------

JETSON_HOST = "192.168.1.84"
JETSON_PORT = 5600

MJPEG_PORT = 5000
MJPEG_WIDTH = 640
MJPEG_HEIGHT = 480
MJPEG_FPS = 15
MJPEG_QUALITY = 80  # JPEG quality (0-100)

GST_PIPELINE = (
    "libcamerasrc ! "
    "video/x-raw,width=640,height=480,framerate=15/1 ! "
    "videoconvert ! "
    "x264enc tune=zerolatency bitrate=1000 ! "
    "rtph264pay config-interval=1 pt=96 ! "
    f"udpsink host={JETSON_HOST} port={JETSON_PORT}"
)

# OpenCV capture pipeline for MJPEG (reads raw frames from libcamera)
CV_PIPELINE = (
    "libcamerasrc ! "
    "video/x-raw,width=640,height=480,framerate=15/1 ! "
    "videoconvert ! "
    "video/x-raw,format=BGR ! "
    "appsink drop=true max-buffers=2"
)

# --- Logging -----------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# --- GStreamer RTP thread -----------------------------------------------------

_gst_proc: subprocess.Popen | None = None
_gst_lock = threading.Lock()


def _gst_worker() -> None:
    """Run GStreamer RTP emitter; restart on failure."""
    global _gst_proc
    cmd = ["gst-launch-1.0", "-e"] + GST_PIPELINE.split()
    while True:
        log.info("GStreamer RTP: starting → %s:%s", JETSON_HOST, JETSON_PORT)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            with _gst_lock:
                _gst_proc = proc
            _, stderr = proc.communicate()
            rc = proc.returncode
            if stderr:
                log.warning("GStreamer stderr: %s", stderr.decode(errors="replace").strip())
            log.warning("GStreamer exited with code %d — restarting in 3 s", rc)
        except Exception as exc:
            log.error("GStreamer launch failed: %s", exc)
        time.sleep(3)


def start_rtp_thread() -> threading.Thread:
    t = threading.Thread(target=_gst_worker, name="gst-rtp", daemon=True)
    t.start()
    return t


# --- MJPEG capture & streaming -----------------------------------------------

_cap: cv2.VideoCapture | None = None
_frame_lock = threading.Lock()
_latest_frame: bytes | None = None


def _capture_worker() -> None:
    """Continuously grab frames from libcamera via GStreamer appsink."""
    global _cap, _latest_frame

    log.info("MJPEG capture: opening libcamerasrc pipeline")
    cap = cv2.VideoCapture(CV_PIPELINE, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        log.error("Failed to open capture pipeline — MJPEG unavailable")
        return

    _cap = cap
    log.info("MJPEG capture: pipeline open")

    while True:
        ok, frame = cap.read()
        if not ok:
            log.warning("MJPEG capture: frame grab failed, retrying…")
            time.sleep(0.1)
            continue
        _, jpg = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, MJPEG_QUALITY]
        )
        with _frame_lock:
            _latest_frame = jpg.tobytes()


def start_capture_thread() -> threading.Thread:
    t = threading.Thread(target=_capture_worker, name="mjpeg-cap", daemon=True)
    t.start()
    return t


def _mjpeg_generator():
    boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
    while True:
        with _frame_lock:
            frame = _latest_frame
        if frame is None:
            time.sleep(0.05)
            continue
        yield boundary + frame + b"\r\n"
        time.sleep(1.0 / MJPEG_FPS)


# --- Flask app ---------------------------------------------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return (
        "<html><body>"
        "<h2>WireClaw Pi Zero — camera feed</h2>"
        '<img src="/stream" />'
        "</body></html>"
    )


@app.route("/stream")
def stream():
    return Response(
        _mjpeg_generator(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/health")
def health():
    with _frame_lock:
        has_frame = _latest_frame is not None
    with _gst_lock:
        gst_alive = _gst_proc is not None and _gst_proc.poll() is None
    status = "ok" if (has_frame and gst_alive) else "degraded"
    return {"status": status, "mjpeg": has_frame, "rtp": gst_alive}


# --- Entrypoint --------------------------------------------------------------

if __name__ == "__main__":
    start_rtp_thread()
    start_capture_thread()

    # Give the pipelines a moment to initialise before accepting connections
    time.sleep(2)

    log.info("Flask MJPEG server starting on port %d", MJPEG_PORT)
    app.run(host="0.0.0.0", port=MJPEG_PORT, threaded=True)
