
# Dashboard Web (Flask + Socket.IO) para Raspberry Pi

Este proyecto crea una **interfaz web** para **monitorear** las temperaturas de los DS18B20 y **controlar** la **bomba** y el **relé V** definidos en tu `sensors.py`.

## Contenido
- `app.py` — Servidor Flask con Socket.IO y un hilo de lectura.
- `templates/index.html` — UI del dashboard.
- `static/app.js` — Lógica del frontend (gráfica y controles).
- `static/styles.css` — Estilos minimalistas oscuros.

## Requisitos
```bash
sudo apt-get update
sudo apt-get install -y python3-pip
pip3 install flask flask-socketio eventlet RPi.GPIO
# Chart.js y Socket.IO client se cargan por CDN
```

## Cómo ejecutar
```bash
# Ubícate en la carpeta del proyecto
python3 app.py
```
Luego abre en el navegador: `http://<IP-de-tu-RPi>:5000`

> Nota: el servidor corre en `0.0.0.0:5000`, accesible en tu LAN.

## Cómo funciona
- Importa tu `sensors.py` y usa sus funciones: `bomba_on/off()`, `rele_v_on/off()`, `descubrir_sensores_28()`, `leer_ds18b20(path)`.
- Un **hilo de fondo** lee cada `INTERVALO_SEG` (valor desde `sensors.py` si existe) y emite datos a todos los clientes conectados mediante **Socket.IO**.
- La UI muestra: temperaturas por sensor, promedio, estados de **bomba**, **relé V** y **trigger**, además de una **gráfica** en vivo.
- Botones permiten encender/apagar **bomba** y **relé V** vía `/api/bomba` y `/api/relev` (POST JSON `{"action":"on"|"off"}`).

## Sugerencias
- Si tu `sensors.py` ya ejecuta un proceso principal, corre **solo** `app.py` (no el `main()` del otro) o divide `sensors.py` en **módulo** (funciones) y **script** (main).
- Para producción, puedes crear un servicio systemd.

### Ejemplo de servicio systemd
`/etc/systemd/system/pi-dashboard.service`
```
[Unit]
Description=Pi Dashboard (Flask + SocketIO)
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/pi_dashboard/app.py
WorkingDirectory=/home/pi/pi_dashboard
Restart=always
User=pi
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Luego:
```bash
sudo systemctl daemon-reload
sudo systemctl enable pi-dashboard
sudo systemctl start pi-dashboard
sudo journalctl -u pi-dashboard -f
```

## Seguridad básica
- La app no implementa autenticación. En redes abiertas o si expones hacia Internet, añade login y reverse proxy con TLS (Nginx + basic auth o JWT).
- Evita ejecutar como `root` si no es necesario.
