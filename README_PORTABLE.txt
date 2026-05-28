EcoSensor Servidor Portable
===========================

Uso recomendado
---------------

1. La primera vez:
   - Clic derecho sobre run.bat
   - Ejecutar como administrador
   - Esto permite crear/verificar la regla de Firewall para el puerto TCP 8765.

2. Las siguientes veces:
   - Doble clic normal sobre run.bat.

Direcciones
-----------

En la misma computadora:

    http://localhost:8765

Desde otro equipo en la misma red:

    http://IP_DE_ESTA_PC:8765

O por mDNS si la red lo permite:

    http://ecosensor-servidor.local:8765

Datos de la aplicacion
----------------------

La app guarda datos en:

    %LOCALAPPDATA%\EcoSensor Servidor

Ahi se guardan:

- settings.json
- measurements.sqlite3
- measurements_ecosensorXX.sqlite3
- storage interno de NiceGUI

Notas
-----

- No mover ni borrar la carpeta python.
- No mover ni borrar la carpeta app.
- Si el firewall bloquea conexiones desde otros equipos, ejecuta run.bat como administrador una vez.
- Si el puerto 8765 esta ocupado, cierra la otra aplicacion o cambia el puerto con la variable ECOSENSOR_SERVER_PORT.
