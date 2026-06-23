import atexit
import ipaddress
import socket
from typing import Optional

from zeroconf import NonUniqueNameException, ServiceInfo, Zeroconf

from config import DISABLE_MDNS, MDNS_HOSTNAME, MDNS_SERVICE_TYPE, UI_PORT

_zeroconf: Optional[Zeroconf] = None
_service_info: Optional[ServiceInfo] = None
PRINT_MDNS_STATUS = True


def _is_useful_lan_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.version == 4 and not ip.is_loopback and not ip.is_unspecified and not ip.is_link_local


def _add_ip(addresses: list[str], value: str | None) -> None:
    if value and _is_useful_lan_ip(value) and value not in addresses:
        addresses.append(value)


def _route_ip_for_target(host: str, port: int) -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((host, port))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _get_lan_ips() -> list[str]:
    """Return useful local IPv4 addresses without requiring internet access.

    En redes AP aisladas (por ejemplo una Raspberry Pi en modo AP sin internet),
    escoger IP usando solo 8.8.8.8 puede fallar o elegir una interfaz incorrecta.
    Por eso anunciamos todas las IPv4 LAN útiles en mDNS.
    """
    addresses: list[str] = []

    # Ruta multicast mDNS: funciona incluso sin internet en una LAN/AP local.
    _add_ip(addresses, _route_ip_for_target('224.0.0.251', 5353))

    # Ruta externa: útil en redes normales con internet.
    _add_ip(addresses, _route_ip_for_target('8.8.8.8', 80))

    # Direcciones asociadas al hostname local.
    try:
        for item in socket.gethostbyname_ex(socket.gethostname())[2]:
            _add_ip(addresses, item)
    except OSError:
        pass

    if not addresses:
        addresses.append('127.0.0.1')
    return addresses


def start_mdns_service() -> None:
    """Advertise the NiceGUI HTTP server as ecosensor-servidor.local."""
    global _zeroconf, _service_info

    if DISABLE_MDNS:
        if PRINT_MDNS_STATUS:
            print('Servidor mDNS deshabilitado por ECOSENSOR_DISABLE_MDNS.', flush=True)
        return

    if _zeroconf is not None:
        return

    ips = _get_lan_ips()
    service_name = f'{MDNS_HOSTNAME}.{MDNS_SERVICE_TYPE}'
    server_name = f'{MDNS_HOSTNAME}.local.'

    _service_info = ServiceInfo(
        MDNS_SERVICE_TYPE,
        service_name,
        addresses=[socket.inet_aton(ip) for ip in ips],
        port=UI_PORT,
        properties={
            'path': '/',
            'name': 'EcoSensor Servidor',
        },
        server=server_name,
    )
    _zeroconf = Zeroconf(interfaces=ips)
    try:
        _zeroconf.register_service(_service_info)
    except NonUniqueNameException:
        _zeroconf.close()
        _zeroconf = None
        _service_info = None
        if PRINT_MDNS_STATUS:
            print(
                f"Servidor mDNS no anunciado: el nombre {MDNS_HOSTNAME}.local ya esta en uso.",
                flush=True,
            )
        return
    if PRINT_MDNS_STATUS:
        ip_list = ', '.join(ips)
        print(f'Servidor mDNS: http://{MDNS_HOSTNAME}.local:{UI_PORT}/ ({ip_list})', flush=True)


def stop_mdns_service() -> None:
    global _zeroconf, _service_info

    if _zeroconf is None or _service_info is None:
        return

    try:
        _zeroconf.unregister_service(_service_info)
    finally:
        _zeroconf.close()
        _zeroconf = None
        _service_info = None


atexit.register(stop_mdns_service)
