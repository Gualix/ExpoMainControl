import os
import time
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import RPi.GPIO as GPIO

# Importar módulo de sensores
import sys
sys.path.append("/mnt/data")
import sensors as S

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-me"
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# Configuraciones ajustables
POLL_SEC = float(os.getenv("POLL_SEC", getattr(S, "INTERVALO_SEG", 2.0)))  # lectura
EMIT_SEC = float(os.getenv("EMIT_SEC", "4.0"))  # emisión a la web
DELTA_EPS = float(os.getenv("DELTA_EPS", "0.05"))  # cambio mínimo para emitir

_state = {"sensors": [], "last_read": None, "temps": {}, "avg": None}

# --- Inicialización GPIO ---
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
for pin in [getattr(S, "BOMBA_PIN", None), getattr(S, "RELE_V_PIN", None)]:
    if isinstance(pin, int):
        try:
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        except Exception:
            pass
if isinstance(getattr(S, "TRIGGER_PIN", None), int):
    try:
        GPIO.setup(S.TRIGGER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    except Exception:
        pass

# --- Funciones principales ---
def read_all_temperatures():
    temps = {}
    ids = _state["sensors"]
    for idx in range(3):
        alias = S.SENSOR_ALIASES[idx] if idx < len(S.SENSOR_ALIASES) else f"sensor_{idx+1}"
        if idx < len(ids):
            try:
                t = S.leer_ds18b20(ids[idx]["path"])
            except Exception:
                t = None
        else:
            t = None
        temps[alias] = t
    valid = [t for t in temps.values() if isinstance(t, (int, float))]
    avg = round(sum(valid)/len(valid), 3) if valid else None
    return temps, avg

def discover_once():
    ids = S.descubrir_sensores_28()
    _state["sensors"] = [{"alias": a, "path": p} for a, p in zip(S.SENSOR_ALIASES, ids[:3])]

def gpio_status():
    def safe_in(pin, default=None):
        try:
            return GPIO.input(pin)
        except Exception:
            return default
    return {
        "bomba": safe_in(getattr(S, "BOMBA_PIN", 0), None),
        "relay_v": safe_in(getattr(S, "RELE_V_PIN", 0), None),
        "trigger": safe_in(getattr(S, "TRIGGER_PIN", 0), None),
    }

def temps_changed(new, old, eps):
    if old is None:
        return True
    for k in new:
        a, b = new.get(k), old.get(k)
        if a is None or b is None:
            return True
        if abs(a - b) > eps:
            return True
    return False

# --- Hilo de lectura en background ---
def background_reader():
    discover_once()
    last_emit = 0
    last_temps = None
    last_avg = None

    while True:
        try:
            temps, avg = read_all_temperatures()
            _state["temps"] = temps
            _state["avg"] = avg
            _state["last_read"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            now = time.time()
            if (now - last_emit) >= EMIT_SEC or temps_changed(temps, last_temps, DELTA_EPS) \
               or (avg and last_avg and abs(avg - last_avg) > DELTA_EPS):
                socketio.emit("telemetry", {
                    "temps": temps,
                    "avg": avg,
                    "ts": _state["last_read"],
                    "gpio": gpio_status()
