from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import AsyncMock, patch

from services import wifi_manager


class _DisconnectingHandler(BaseHTTPRequestHandler):
    def do_DELETE(self) -> None:
        self.connection.shutdown(2)
        self.connection.close()

    def log_message(self, *_args) -> None:
        pass


class WifiClearTests(unittest.IsolatedAsyncioTestCase):
    @patch('services.wifi_manager.delete_json', new_callable=AsyncMock)
    @patch('services.wifi_manager.probe_host', new_callable=AsyncMock)
    async def test_normal_response_is_confirmed(self, probe, delete):
        probe.return_value = {'device_id': 'ecosensor03', 'host': '192.0.2.3'}
        delete.return_value = {'ok': True, 'status': 200, 'data': {'ok': True}}

        result = await wifi_manager.clear_device_wifi('ecosensor03', '192.0.2.3')

        self.assertTrue(result['ok'])
        self.assertTrue(result['confirmed'])

    @patch('services.wifi_manager.probe_host', new_callable=AsyncMock)
    async def test_restart_disconnect_is_reported_as_unconfirmed_success(self, probe):
        probe.return_value = {'device_id': 'ecosensor03', 'host': '127.0.0.1'}
        server = HTTPServer(('127.0.0.1', 0), _DisconnectingHandler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            result = await wifi_manager.clear_device_wifi(
                'ecosensor03', f'127.0.0.1:{server.server_port}',
            )
        finally:
            thread.join(timeout=2.0)
            server.server_close()

        self.assertTrue(result['ok'])
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['response']['status'], 0)

    @patch('services.wifi_manager.delete_json', new_callable=AsyncMock)
    @patch('services.wifi_manager.probe_host', new_callable=AsyncMock)
    async def test_identity_mismatch_does_not_send_delete(self, probe, delete):
        probe.return_value = {'device_id': 'ecosensor02', 'host': '192.0.2.3'}

        result = await wifi_manager.clear_device_wifi('ecosensor03', '192.0.2.3')

        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'device_identity_mismatch')
        delete.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
