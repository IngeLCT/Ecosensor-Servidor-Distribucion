import asyncio
import socket
import unittest
from unittest.mock import MagicMock, patch

from services import device_registry


class DeviceRegistryResolverTests(unittest.TestCase):
    def test_ip_is_returned_without_dns_lookup(self) -> None:
        with patch('services.device_registry.socket.getaddrinfo') as getaddrinfo:
            result = device_registry._resolve_host_quick_sync('192.168.1.44')

        self.assertEqual(result, '192.168.1.44')
        getaddrinfo.assert_not_called()

    def test_local_name_uses_native_cross_platform_resolver(self) -> None:
        resolved = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.1.52', 0)),
        ]
        with patch('services.device_registry.socket.getaddrinfo', return_value=resolved) as getaddrinfo:
            result = device_registry._resolve_host_quick_sync('ecosensor03.local')

        self.assertEqual(result, '192.168.1.52')
        getaddrinfo.assert_called_once_with(
            'ecosensor03.local',
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        )

    def test_unresolved_local_name_returns_none(self) -> None:
        with patch(
            'services.device_registry.socket.getaddrinfo',
            side_effect=socket.gaierror('host not found'),
        ):
            result = device_registry._resolve_host_quick_sync('ecosensor12.local')

        self.assertIsNone(result)

    def test_async_resolver_enforces_timeout(self) -> None:
        async def slow_resolver(_function, _host: str) -> str | None:
            await asyncio.sleep(0.05)
            return '192.168.1.52'

        with patch('services.device_registry.asyncio.to_thread', side_effect=slow_resolver):
            result = asyncio.run(device_registry._resolve_host_quick('ecosensor03.local', timeout=0.001))

        self.assertIsNone(result)

    def test_local_addresses_use_windows_compatible_socket_apis(self) -> None:
        route_socket = MagicMock()
        route_socket.__enter__.return_value.getsockname.return_value = ('192.168.1.20', 50000)
        resolved = [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('192.168.1.20', 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('10.20.30.40', 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('127.0.0.1', 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('169.254.4.8', 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, '', ('8.8.8.8', 0)),
        ]
        with (
            patch('services.device_registry.socket.socket', return_value=route_socket),
            patch('services.device_registry.socket.gethostname', return_value='WINDOWS-PC'),
            patch('services.device_registry.socket.getaddrinfo', return_value=resolved) as getaddrinfo,
        ):
            addresses = device_registry._local_ipv4_addresses()

        self.assertEqual(addresses, ['192.168.1.20', '10.20.30.40'])
        getaddrinfo.assert_called_once_with(
            'WINDOWS-PC',
            None,
            family=socket.AF_INET,
            type=socket.SOCK_DGRAM,
        )


if __name__ == '__main__':
    unittest.main()
