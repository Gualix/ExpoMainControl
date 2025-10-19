#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
===============================================================================
 Proyecto: Monitoreo DS18B20 + Control de Bomba (ExpoTEC 2025)
 Plataforma: Raspberry Pi 4 (Raspberry Pi OS)


Actualizado al 10 de agosto, 2025
 Descripción:
   - Lee 3 sensores DS18B20 (bus 1-Wire en GPIO4).
   - Calcula el promedio de las lecturas válidas.
   - Activa una bomba (módulo de relé) si el promedio supera un umbral configurable.
   - Registra las lecturas en CSV dentro de 'mediciones/', creando un archivo nuevo
     en cada ejecución. El nombre del archivo inicia con la fecha de inicio y agrega
     la hora para garantizar unicidad. Agrega una columna 'consecutivo' por fila.

 Conexiones:
   DS18B20 (x3, bus compartido):
     * DATA  -> GPIO4 (BCM 4, pin físico 7)
     * VCC   -> 3.3V (pin 1 o 17)
     * GND   -> GND  (pin 6/9/14...)
     * Resistencia 4.7kΩ entre DATA y 3.3V (pull-up)

   Módulo de relé (bomba):
     * IN    -> GPIO27 (BCM 27, pin físico 11)
     * GND   -> GND Raspberry
     * VCC   -> 5V (según módulo)
   Nota: Muchos módulos son "active LOW": se activan con nivel lógico bajo.

 Requisitos:
   - Habilitar 1-Wire: `sudo raspi-config` -> Interface Options -> 1-Wire -> Enable
   - Instalar GPIO:     `sudo apt-get install -y python3-rpi.gpio`

===============================================================================
"""

import time
from pathlib import Path
from datetime import datetime
import RPi.GPIO as GPIO

# ============================================================================
# CONFIGURACIÓN RÁPIDA 
# ============================================================================
UMBRAL_ACTIVACION_C = 22.0   # Umbral de Temperatura: bomba ON si promedio > este valor (°C)
INTERVALO_SEG = 5            # Intervalo de muestreo en segundos

BOMBA_PIN = 27               

# --- Nuevo: pines para monitor y relé V ---
# Pin de entrada que se leerá constantemente (BCM).
TRIGGER_PIN = 23   # < Este es el pin que lee la entrada
# Salida para el relé V (BCM).
RELE_V_PIN  = 22   # <-- Aqui se conecta el nuevo rele
#-----------------------------------------------------------------------------

# GPIO BCM del módulo de bomba (relé)
BOMBA_ACTIVE_LEVEL = 1       # 0 = active LOW (común), 1 = active HIGH

SENSOR_ALIASES = ["sensor_1", "sensor_2", "sensor_3"]

# ----------------------------------------------------------------------------
# Ajustes internos
# ----------------------------------------------------------------------------
W1_BASE = Path("/sys/bus/w1/devices")
MEDICIONES_DIR = Path("mediciones")   # Carpeta de salida para CSV
REINTENTOS = 3
ESPERA_REINTENTO = 0.2  # s

# (Se define LOG_FILE dinámicamente en runtime para que cada ejecución cree uno nuevo)
LOG_FILE = None

# Contador de mediciones (consecutivo por fila)
consecutivo = 0

# ============================================================================
# Utilidades de archivo / nombres
# ============================================================================
def preparar_archivo_log():
    """
    Crea la carpeta 'mediciones/' si no existe y genera un nombre de archivo
    único que comience con la fecha (YYYY-MM-DD) y la hora (HH-MM-SS) del inicio.
    Devuelve la ruta completa del CSV.
    """
    MEDICIONES_DIR.mkdir(parents=True, exist_ok=True)
    run_ts = datetime.now()
    fname = f"{run_ts.strftime('%Y-%m-%d_%H-%M-%S')}_temperaturas.csv"
    return MEDICIONES_DIR / fname

def inicializar_log(aliases):
    """
    Crea el CSV con cabecera si no existe:
    timestamp_local, sensor_1, sensor_2, sensor_3, avg_c, bomba_state, consecutivo
    """
    header = ["timestamp_local"] + aliases + ["avg_c", "bomba_state", "consecutivo"]
    if not LOG_FILE.exists():
        LOG_FILE.write_text(",".join(header) + "\n", encoding="utf-8")

def anexar_csv(fila):
    """Agrega una línea CSV (lista de strings) al archivo de log."""
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(",".join(fila) + "\n")

# ============================================================================
# Sensor DS18B20
# ============================================================================
def descubrir_sensores_28():
    """Lista rutas a carpetas 28-... (sensores) ordenadas alfabéticamente."""
    if not W1_BASE.exists():
        return []
    sensores = [p for p in W1_BASE.iterdir() if p.name.startswith("28-")]
    sensores.sort(key=lambda p: p.name)
    return sensores

def leer_ds18b20(sensor_path):
    """
    Lee temperatura en °C desde w1_slave con verificación de CRC ('YES').
    Devuelve float o None si falla.
    """
    w1_file = sensor_path / "w1_slave"
    for _ in range(REINTENTOS):
        try:
            with w1_file.open("r") as f:
                lines = f.read().strip().splitlines()
            if len(lines) >= 2 and lines[0].strip().endswith("YES"):
                parts = lines[1].split("t=")
                if len(parts) == 2 and parts[1].strip().lstrip("-").isdigit():
                    milic = int(parts[1])
                    return milic / 1000.0
        except Exception:
            pass
        time.sleep(ESPERA_REINTENTO)
    return None

# ============================================================================
# Control de bomba (relé)
# ============================================================================
def _nivel_activo():
    return GPIO.LOW if BOMBA_ACTIVE_LEVEL == 0 else GPIO.HIGH

def _nivel_inactivo():
    return GPIO.HIGH if BOMBA_ACTIVE_LEVEL == 0 else GPIO.LOW

def bomba_setup():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BOMBA_PIN, GPIO.OUT, initial=_nivel_inactivo())

def bomba_on():
    GPIO.output(BOMBA_PIN, _nivel_activo())

def bomba_off():
    GPIO.output(BOMBA_PIN, _nivel_inactivo())


# ---------------- Nuevas utilidades: Relé V e input de disparo ----------------
def rele_v_setup():
    """Configura el pin del relé V como salida."""
    GPIO.setup(RELE_V_PIN, GPIO.OUT, initial=_nivel_inactivo())

def rele_v_on():
    GPIO.output(RELE_V_PIN, _nivel_activo())

def rele_v_off():
    GPIO.output(RELE_V_PIN, _nivel_inactivo())

def _on_trigger_edge(channel):
    """Callback cuando cambia el pin de entrada.
    Si está en alto -> enciende relé V; si está en bajo -> apaga relé V."""
    try:
        val = GPIO.input(TRIGGER_PIN)
        if val:
            rele_v_on()
        else:
            rele_v_off()
    except Exception as e:
        print(f"[WARN] Callback trigger falló: {e}")

def trigger_setup():
    """Configura el pin TRIGGER_PIN como entrada con PULL-DOWN y detección por interrupciones."""
    GPIO.setup(TRIGGER_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    # Detección en ambos flancos para reflejar ON/OFF del relé V según el estado del pin
    GPIO.add_event_detect(TRIGGER_PIN, GPIO.BOTH, callback=_on_trigger_edge, bouncetime=150)

def gpio_setup_all():
    """Inicializa GPIO y configura bomba, relé V y el pin de disparo."""
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    # Salidas
    bomba_setup()
    rele_v_setup()
    # Entradas + eventos
    trigger_setup()

# ============================================================================
# Programa principal
# ============================================================================
def main():
    global LOG_FILE, consecutivo

    # 1- Preparar archivo de salida único por ejecución
    LOG_FILE = preparar_archivo_log()
    print(f"Archivo de salida: {LOG_FILE}")

    # 2- Detectar sensores y mapear 3 primeros a sensor_1..sensor_3
    sensores_28 = descubrir_sensores_28()
    if len(sensores_28) < 3:
        print(f"[AVISO] Se detectaron {len(sensores_28)} sensores DS18B20; se esperan 3.")
    sensores_asignados = sensores_28[:3]
    if not sensores_asignados:
        print("No se encontraron sensores '28-'. Revisa 1-Wire y conexiones.")
        return

    print("Mapeo sensores (alias -> ID):")
    for alias, path in zip(SENSOR_ALIASES, sensores_asignados):
        print(f"  {alias} -> {path.name}")

    # 3- Iniciar CSV y GPIO de bomba
    inicializar_log(SENSOR_ALIASES)
    gpio_setup_all()
    bomba_off()
    estado_bomba = False

    try:
        while True:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 4- Leer 3 sensores (rellena con None si faltan)
            lecturas = []
            for i in range(3):
                if i < len(sensores_asignados):
                    t = leer_ds18b20(sensores_asignados[i])
                else:
                    t = None
                lecturas.append(t)

            # 5- Promedio con solo lecturas válidas
            validas = [t for t in lecturas if t is not None]
            avg = (sum(validas) / len(validas)) if validas else None

            # 6- Lógica de control: ON si avg > umbral
            if avg is not None and avg > UMBRAL_ACTIVACION_C:
                bomba_on()
                estado_bomba = True
            else:
                bomba_off()
                estado_bomba = False

            # 7- Construir y guardar fila CSV
            consecutivo += 1
            fila_vals = [("" if t is None else f"{t:.3f}") for t in lecturas]
            avg_str = "" if avg is None else f"{avg:.3f}"
            bomba_str = "ON" if estado_bomba else "OFF"
            fila = [ts] + fila_vals + [avg_str, bomba_str, str(consecutivo)]
            anexar_csv(fila)

            # 8- Consola
            pretty = " | ".join(
                f"{alias}: {(f'{t:.3f} °C' if t is not None else 'N/A')}"
                for alias, t in zip(SENSOR_ALIASES, lecturas)
            )
            print(
                f"[{ts}] {pretty} | avg: {avg_str or 'N/A'} °C "
                f"| umbral: {UMBRAL_ACTIVACION_C:.2f} °C | bomba: {bomba_str} "
                f"| consecutivo: {consecutivo}"
            )

            time.sleep(INTERVALO_SEG)

    except KeyboardInterrupt:
        print("\nFinalizado por el usuario.")
    finally:
        bomba_off()
        rele_v_off()
        GPIO.cleanup()
        print("GPIO limpio. CSV en:", LOG_FILE.resolve())

if __name__ == "__main__":
    main()

#------------------ Fin del Código ----------------------
