from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services import history_reset_state as reset_state
from services import measurement_sync
from storage import measurements_store as store


ZERO_STATUS = {
    'device_id': 'ecosensor03',
    'sd_ready': True,
    'sd_last_id': 0,
    'last_measurement_id': 0,
    'checkpoint_valid': True,
    'checkpoint_current': True,
    'history_index_ready': True,
    'history_index_points': 0,
}


class HistoryResetStateTests(unittest.TestCase):
    def tearDown(self):
        reset_state.finish_history_reset('ecosensor03', confirmed=False)

    def test_push_is_rejected_during_reset(self):
        reset_state.begin_history_reset('ecosensor03')
        self.assertEqual(reset_state.accept_push_id('ecosensor03', 14880), (False, 'history_reset_in_progress'))

    def test_only_id_one_is_accepted_after_confirmed_reset(self):
        reset_state.begin_history_reset('ecosensor03')
        reset_state.finish_history_reset('ecosensor03', confirmed=True)
        self.assertEqual(reset_state.accept_push_id('ecosensor03', 14880), (False, 'awaiting_measurement_id_1'))
        self.assertEqual(reset_state.accept_push_id('ecosensor03', 1), (True, ''))
        self.assertEqual(reset_state.accept_push_id('ecosensor03', 2), (True, ''))


class CoordinatedHistoryResetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        store.DATA_DIR = root
        store.MEASUREMENTS_DB_FILE = root / 'measurements.sqlite3'
        store.save_measurement('192.168.1.30', {
            'device_id': 'ecosensor03', 'measurement_id': 14880,
            'timestamp': '2026-07-20T19:00:00Z', 'time_valid': True,
        })

    def tearDown(self):
        reset_state.finish_history_reset('ecosensor03', confirmed=False)
        self.temp_dir.cleanup()

    @patch('services.measurement_sync.mark_device_seen')
    @patch('services.measurement_sync.invalidate_device_status')
    @patch('services.measurement_sync.fetch_json', new_callable=AsyncMock)
    @patch('services.measurement_sync.delete_json', new_callable=AsyncMock)
    @patch('services.measurement_sync.ensure_device_active', new_callable=AsyncMock)
    async def test_remote_zero_confirmed_before_sqlite_clear(self, active, delete, fetch, invalidate, mark):
        active.return_value = {'device_id': 'ecosensor03', 'host': '192.168.1.30', 'status': {'sd_last_id': 14880}}
        delete.return_value = {'ok': True, 'status': 200, 'data': {'ok': True}}
        fetch.return_value = {'ok': True, 'status': 200, 'data': dict(ZERO_STATUS)}
        result = await measurement_sync.coordinated_clear_history('ecosensor03')
        self.assertTrue(result['ok'])
        self.assertEqual(result['deleted'], 1)
        self.assertIsNone(store.get_latest_measurement('ecosensor03'))
        self.assertEqual(reset_state.accept_push_id('ecosensor03', 14880)[0], False)
        self.assertEqual(reset_state.accept_push_id('ecosensor03', 1), (True, ''))

    @patch('services.measurement_sync.fetch_json', new_callable=AsyncMock)
    @patch('services.measurement_sync.delete_json', new_callable=AsyncMock)
    @patch('services.measurement_sync.ensure_device_active', new_callable=AsyncMock)
    async def test_stale_high_remote_status_does_not_clear_sqlite(self, active, delete, fetch):
        active.return_value = {'device_id': 'ecosensor03', 'host': '192.168.1.30'}
        delete.return_value = {'ok': True, 'status': 200, 'data': {'ok': True}}
        fetch.return_value = {'ok': True, 'status': 200, 'data': {**ZERO_STATUS, 'sd_last_id': 14880}}
        result = await measurement_sync.coordinated_clear_history('ecosensor03')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'remote_clear_not_confirmed')
        self.assertIsNotNone(store.get_latest_measurement('ecosensor03'))

    @patch('services.measurement_sync.delete_json', new_callable=AsyncMock)
    @patch('services.measurement_sync.ensure_device_active', new_callable=AsyncMock)
    async def test_remote_error_preserves_sqlite(self, active, delete):
        active.return_value = {'device_id': 'ecosensor03', 'host': '192.168.1.30'}
        delete.return_value = {'ok': False, 'status': 500, 'data': 'error'}
        result = await measurement_sync.coordinated_clear_history('ecosensor03')
        self.assertEqual(result['error'], 'remote_clear_failed')
        self.assertIsNotNone(store.get_latest_measurement('ecosensor03'))


if __name__ == '__main__':
    unittest.main()
