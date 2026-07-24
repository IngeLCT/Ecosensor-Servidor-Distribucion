import unittest
from unittest.mock import AsyncMock, patch

from config import get_selected_ui_port, set_selected_ui_port
from services.esp_client import push_host_payload, system_datetime_payload
from services.measurement_sync import _configure_push_host_if_needed, _push_target_differs


class PushTargetPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_port = get_selected_ui_port()

    def tearDown(self) -> None:
        set_selected_ui_port(self.previous_port)

    @patch('services.esp_client._local_ip_for_target', return_value='192.168.1.50')
    def test_push_payload_includes_selected_port(self, _mock_ip) -> None:
        set_selected_ui_port(8777)
        self.assertEqual(
            push_host_payload('ecosensor01.local'),
            {'push_host': '192.168.1.50', 'push_port': 8777},
        )

    @patch('services.esp_client._local_ip_for_target', return_value='192.168.1.50')
    def test_time_payload_includes_same_push_target(self, _mock_ip) -> None:
        set_selected_ui_port(80)
        payload = system_datetime_payload('ecosensor01.local')
        self.assertEqual(payload['push_host'], '192.168.1.50')
        self.assertEqual(payload['push_port'], 80)


class PushTargetComparisonTests(unittest.TestCase):
    def test_matching_target_is_not_different(self) -> None:
        self.assertFalse(
            _push_target_differs(
                {'push_host': '192.168.1.50', 'push_port': 8766},
                {'push_host': '192.168.1.50', 'push_port': 8766},
            )
        )

    def test_host_or_port_difference_is_detected(self) -> None:
        expected = {'push_host': '192.168.1.50', 'push_port': 8766}
        self.assertTrue(_push_target_differs({'push_host': '192.168.1.99', 'push_port': 8766}, expected))
        self.assertTrue(_push_target_differs({'push_host': '192.168.1.50', 'push_port': 8765}, expected))
        self.assertTrue(_push_target_differs({'push_host': None, 'push_port': 80}, expected))


class PushTargetImmediateUpdateTests(unittest.IsolatedAsyncioTestCase):
    @patch(
        'services.measurement_sync.configure_push_host',
        new_callable=AsyncMock,
        return_value={'ok': True, 'push_host': '192.168.1.50', 'push_port': 8766},
    )
    @patch(
        'services.measurement_sync.push_host_payload',
        return_value={'push_host': '192.168.1.50', 'push_port': 8766},
    )
    async def test_port_mismatch_updates_without_waiting_for_overdue(
        self,
        _mock_payload,
        mock_configure,
    ) -> None:
        await _configure_push_host_if_needed(
            'ecosensor01',
            'ecosensor01.local',
            None,
            {'push_host': '192.168.1.50', 'push_port': 8765, 'can_push': True},
        )
        mock_configure.assert_awaited_once_with('ecosensor01.local', timeout=3.0)

    @patch('services.measurement_sync.configure_push_host', new_callable=AsyncMock)
    @patch(
        'services.measurement_sync.push_host_payload',
        return_value={'push_host': '192.168.1.50', 'push_port': 8766},
    )
    async def test_matching_target_does_not_send_redundant_update(
        self,
        _mock_payload,
        mock_configure,
    ) -> None:
        await _configure_push_host_if_needed(
            'ecosensor01',
            'ecosensor01.local',
            None,
            {'push_host': '192.168.1.50', 'push_port': 8766, 'can_push': True},
        )
        mock_configure.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
