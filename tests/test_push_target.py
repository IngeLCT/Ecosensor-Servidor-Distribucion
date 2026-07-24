import unittest
from unittest.mock import patch

from config import get_selected_ui_port, set_selected_ui_port
from services.esp_client import push_host_payload, system_datetime_payload


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


if __name__ == '__main__':
    unittest.main()
