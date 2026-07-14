"""Ayudante manual para validar arranque de EcoSensor con puertos ocupados.

Ejemplos:
  # Ocupar 80 y 8765 con procesos que NO son EcoSensor:
  python scripts/port_startup_test_helper.py --ports 80,8765

  # Simular una instancia EcoSensor existente en 8765:
  python scripts/port_startup_test_helper.py --ecosensor-health-port 8765

Deja este proceso abierto y arranca EcoSensor en otra terminal.
Detenlo con Ctrl+C al terminar la prueba.
"""
from __future__ import annotations

import argparse
import json
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler


class EcoSensorHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - nombre requerido por BaseHTTPRequestHandler
        if self.path != '/api/health':
            self.send_response(404)
            self.end_headers()
            return

        payload = json.dumps({'ok': True, 'service': 'EcoSensor Servidor'}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _hold_plain_tcp_port(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('0.0.0.0', port))
    sock.listen(1)
    return sock


def _start_fake_ecosensor_health(port: int) -> ReusableTCPServer:
    server = ReusableTCPServer(('127.0.0.1', port), EcoSensorHealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _parse_ports(raw: str) -> list[int]:
    ports: list[int] = []
    for part in raw.split(','):
        part = part.strip()
        if part:
            ports.append(int(part))
    return ports


def main() -> None:
    parser = argparse.ArgumentParser(description='Ocupa puertos locales para probar el arranque robusto de EcoSensor.')
    parser.add_argument('--ports', default='', help='Puertos TCP a ocupar sin responder como EcoSensor. Ejemplo: 80,8765')
    parser.add_argument('--ecosensor-health-port', type=int, help='Puerto donde simular /api/health de EcoSensor existente.')
    args = parser.parse_args()

    sockets: list[socket.socket] = []
    servers: list[ReusableTCPServer] = []

    try:
        for port in _parse_ports(args.ports):
            sockets.append(_hold_plain_tcp_port(port))
            print(f'Puerto ocupado sin EcoSensor: {port}', flush=True)

        if args.ecosensor_health_port:
            servers.append(_start_fake_ecosensor_health(args.ecosensor_health_port))
            print(f'Simulando EcoSensor existente en: http://127.0.0.1:{args.ecosensor_health_port}/api/health', flush=True)

        if not sockets and not servers:
            parser.error('Indica --ports y/o --ecosensor-health-port')

        print('Ayudante activo. Arranca EcoSensor en otra terminal. Ctrl+C para salir.', flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('\nCerrando ayudante...', flush=True)
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for sock in sockets:
            sock.close()


if __name__ == '__main__':
    main()
