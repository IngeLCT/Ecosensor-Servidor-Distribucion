# EcoSensor Servidor - Distribución

Versión limpia para prueba de distribución.

## Funciones incluidas

- Dashboard local con NiceGUI.
- Detección de EcoSensores activos por IP/mDNS.
- Sincronización de fecha/hora del EcoSensor.
- Recepción de mediciones por `POST /api/measurements/push`.
- Sincronización de historial desde el EcoSensor como respaldo.
- Gráficas e historial local en SQLite.
- Exportación CSV de mediciones.
- Mantenimiento básico:
  - borrar credenciales WiFi del EcoSensor mediante `/wifi/clear`
  - borrar historial de mediciones local/remoto

## Ejecutar

```bash
python main.py
```

Por defecto escucha en:

```text
http://localhost:8765
```

Variables opcionales:

```bash
ECOSENSOR_SERVER_HOST=0.0.0.0
ECOSENSOR_SERVER_PORT=8765
ECOSENSOR_MDNS_HOSTNAME=ecosensor-servidor
```

## Estructura principal

```text
main.py                 # entrada de la aplicación
config.py               # rutas y configuración base
pages/                  # pantallas NiceGUI
services/               # comunicación con EcoSensor y sincronización
storage/                # SQLite/configuración local
shared/                 # estilos y formateadores
static/                 # imágenes, CSS y JS de la UI
```

## Notas de distribución

- La carpeta `data/` se crea en ejecución.
- No se incluye `.venv`; instalar dependencias con `requirements.txt`.
- No se incluyen cachés, configuración de IDE ni archivos Git.
