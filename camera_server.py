#!/usr/bin/env python3
"""
WireClaw — Pi Zero 2W camera server
Flask API port 5000 : /health  /settings
RTP H264 → Jetson via GStreamer subprocess

Encoder strategy: v4l2h264enc hardware (default) → x264enc software (auto-fallback)
"""

import os
import shlex
import signal
import subprocess
import threading
import time
import logging

from flask import Flask, jsonify, request

# --- Configuration -----------------------------------------------------------

DEFAULTS: dict = {
    "jetson_host": "192.168.1.84",
    "jetson_port": 5600,
    "width": 640,
    "height": 480,
    "fps": 15,
    "bitrate_kbps": 1000,
    # "auto" tries hw then sw; "hw" forces v4l2h264enc; "sw" forces x264enc
    "encoder": "auto",
}

FLASK_PORT = 5000

# --- Logging -----------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# --- Pipeline builder --------------------------------------------------------

def _build_pipeline(cfg: dict, encoder: str) -> str:
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    host, port = cfg["jetson_host"], cfg["jetson_port"]

    sink = f"rtph264pay config-interval=1 pt=96 ! udpsink host={host} port={port}"

    if encoder == "hw":
        bitrate_bps = cfg["bitrate_kbps"] * 1000
        # NV12 format avoids a CPU color-conversion step before v4l2convert
        # level=(string)3.2 is required — default level 1.0 caps at 176x144
        return (
            f"libcamerasrc ! "
            f"video/x-raw,width={w},height={h},format=NV12,framerate={fps}/1 ! "
            f"v4l2convert ! "
            f"v4l2h264enc video-bitrate={bitrate_bps} "
            f'extra-controls="controls,repeat_sequence_header=1" ! '
            f"video/x-h264,level=(string)3.2 ! "
            f"h264parse ! "
            f"{sink}"
        )
    # sw
    return (
        f"libcamerasrc ! "
        f"video/x-raw,width={w},height={h},framerate={fps}/1 ! "
        f"videoconvert ! "
        f"x264enc tune=zerolatency bitrate={cfg['bitrate_kbps']} ! "
        f"{sink}"
    )

# --- GStreamer process manager -----------------------------------------------

class GstManager:
    def __init__(self) -> None:
        self._cfg: dict = dict(DEFAULTS)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._restart_event = threading.Event()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self.encoder_active: str | None = None

    # Public API

    def start(self) -> None:
        self._thread = threading.Thread(target=self._worker, name="gst-rtp", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._shutdown.set()
        self._terminate()

    def restart_with(self, patch: dict) -> None:
        with self._lock:
            self._cfg.update(patch)
        self._terminate()

    def is_alive(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def get_cfg(self) -> dict:
        with self._lock:
            return dict(self._cfg)

    # Internal

    def _terminate(self) -> None:
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _launch(self, encoder: str) -> "subprocess.Popen | None":
        with self._lock:
            cfg = dict(self._cfg)
        pipeline = _build_pipeline(cfg, encoder)
        cmd = ["gst-launch-1.0", "-e"] + shlex.split(pipeline)
        log.info("GStreamer [%s] pipeline: %s", encoder, pipeline)
        try:
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError:
            log.error("gst-launch-1.0 not found in PATH")
            return None

    @staticmethod
    def _drain_stderr(proc: "subprocess.Popen") -> None:
        for line in proc.stderr:
            stripped = line.rstrip()
            if stripped:
                log.debug("gst: %s", stripped)

    def _worker(self) -> None:
        with self._lock:
            pref = self._cfg.get("encoder", "auto")

        if pref == "hw":
            queue = ["hw"]
        elif pref == "sw":
            queue = ["sw"]
        else:
            queue = ["hw", "sw"]

        while not self._shutdown.is_set():
            for enc in queue:
                proc = self._launch(enc)
                if proc is None:
                    continue

                with self._lock:
                    self._proc = proc
                self.encoder_active = enc
                log.info("RTP stream running (encoder=%s)", enc)

                stderr_t = threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True)
                stderr_t.start()

                proc.wait()
                rc = proc.returncode

                if self._shutdown.is_set():
                    return

                log.warning("GStreamer [%s] exited rc=%d", enc, rc)

                if enc == "hw" and pref == "auto":
                    log.warning("Hardware encoder failed — permanent fallback to x264enc")
                    queue = ["sw"]

                break  # restart outer while-loop with updated queue

            if not self._shutdown.is_set():
                log.info("Restarting in 3 s…")
                time.sleep(3)


_gst = GstManager()

# --- Flask app ---------------------------------------------------------------

app = Flask(__name__)


@app.route("/health")
def health():
    alive = _gst.is_alive()
    return jsonify({
        "status": "ok" if alive else "degraded",
        "rtp": alive,
        "encoder": _gst.encoder_active,
    })


@app.route("/settings", methods=["GET"])
def settings_get():
    return jsonify(_gst.get_cfg())


@app.route("/settings", methods=["POST"])
def settings_post():
    data = request.get_json(force=True, silent=True) or {}
    allowed = {"jetson_host", "jetson_port", "width", "height", "fps", "bitrate_kbps", "encoder"}
    patch = {k: v for k, v in data.items() if k in allowed}
    if not patch:
        return jsonify({"error": "no valid fields", "allowed": sorted(allowed)}), 400
    _gst.restart_with(patch)
    return jsonify({"status": "restarting", "applied": patch})


# --- Shutdown ----------------------------------------------------------------

def _on_signal(sig, _frame) -> None:
    log.info("Signal %d — shutting down", sig)
    _gst.stop()
    os._exit(0)


# --- Entrypoint --------------------------------------------------------------

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    _gst.start()
    time.sleep(1)

    log.info("Flask API on 0.0.0.0:%d", FLASK_PORT)
    app.run(host="0.0.0.0", port=FLASK_PORT, threaded=True)
