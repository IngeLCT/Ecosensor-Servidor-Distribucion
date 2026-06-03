EcoSensor Servidor Portable
===========================

Uso recomendado
---------------

1. La primera vez:
 - Ejecuta config.bat
 - Acepta los permisos de administrador cuando Windows los solicite
 - Esto permite crear/verificar la regla de Firewall para el puerto TCP 8765
 - Tambien crea el acceso directo EcoSensor Servidor en el escritorio

2. Las siguientes veces:
 - Usa el acceso directo EcoSensor Servidor del escritorio
 - Este acceso directo inicia el servidor sin abrir consola
 - Para diagnostico manual, ejecuta run.bat

Direccion para acceder a la Aplicacion Web
------------------------------------------

Si no se abrio automaticamente la Aplicacion Web, pega esta direccion en el navegador:

 http://ecosensor-servidor.local:8765

Notas
-----

- No mover ni borrar la carpeta python.
- No mover ni borrar la carpeta app.
- No mover ni borrar run.bat, run_hidden.vbs ni config.bat.
- Si el firewall bloquea conexiones desde otros equipos, ejecuta config.bat una vez.
