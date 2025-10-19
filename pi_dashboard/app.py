
import os
import time
import threading
from datetime import datetime

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
import RPi.GPIO as GPIO

# Importar el módulo de sensores (tu archivo existente)
import sys
sys.path.append("/mnt/data")  # Ajusta esta ruta en tu Pi según la ubicación real
import sensors as S  # Asegúrate de que el archivo se llame sensors.py en la Raspberry

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-me"
socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins="*")

# Estados compartidos
_state = {
    "sensors": [],  # [{"alias": str, "path": str}...]
    "last_read": None,
    "temps": {},    # {"sensor_1": val, ...}
    "avg": None,
}

# Inicialización de GPIO (por si el proceso web inicia solo)
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
# Asegurar salidas definidas en sensors.py
for pin in [getattr(S, "BOMBA_PIN", None), getattr(S, "RELE_V_PIN", None)]:
    if isinstance(pin, int):
        try:
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        except Exception:
            pass
# Entrada TRIGGER_PIN si está
if isinstance(getattr(S, "TRIGGER_PIN", None), int):
    try:
        GPIO.setup(S.TRIGGER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    except Exception:
        pass

def read_all_temperatures():
    """Lee hasta 3 sensores usando utilidades de sensors.py"""
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

def background_reader():
    # Descubrir sensores una vez al iniciar
    discover_once()
    interval = float(getattr(S, "INTERVALO_SEG", 2.0))
    while True:
        try:
            temps, avg = read_all_temperatures()
            _state["temps"] = temps
            _state["avg"] = avg
            _state["last_read"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Emitir a clientes conectados
            socketio.emit("telemetry", {
                "temps": temps, "avg": avg, "ts": _state["last_read"], "gpio": gpio_status()
            })
        except Exception as e:
            socketio.emit("telemetry_error", {"error": str(e)})
        time.sleep(interval)

@app.route("/")
def index():
    return render_template("index.html",
                           sensor_aliases=S.SENSOR_ALIASES,
                           umbral=getattr(S, "UMBRAL_ACTIVACION_C", None))

@app.route("/api/status")
def api_status():
    return jsonify({
        "ts": _state["last_read"],
        "temps": _state.get("temps", {}),
        "avg": _state.get("avg"),
        "gpio": gpio_status(),
    })

@app.route("/api/bomba", methods=["POST"])
def api_bomba():
    action = (request.json or {}).get("action")
    if action == "on":
        S.bomba_on()
    elif action == "off":
        S.bomba_off()
    else:
        return jsonify({"ok": False, "error": "action must be on/off"}), 400
    return jsonify({"ok": True, "gpio": gpio_status()})

@app.route("/api/relev", methods=["POST"])
def api_relev():
    if not hasattr(S, "rele_v_on"):
        return jsonify({"ok": False, "error": "Relé V no disponible en sensors.py"}), 400
    action = (request.json or {}).get("action")
    if action == "on":
        S.rele_v_on()
    elif action == "off":
        S.rele_v_off()
    else:
        return jsonify({"ok": False, "error": "action must be on/off"}), 400
    return jsonify({"ok": True, "gpio": gpio_status()})

@socketio.on("connect")
def on_connect():
    emit("telemetry", {
        "temps": _state.get("temps", {}),
        "avg": _state.get("avg"),
        "ts": _state.get("last_read"),
        "gpio": gpio_status(),
    })

def start_bg():
    t = threading.Thread(target=background_reader, daemon=True)
    t.start()

if __name__ == "__main__":
    start_bg()
    # En Raspberry usa host=0.0.0.0 para acceder desde la red local
    socketio.run(app, host="0.0.0.0", port=5000)
