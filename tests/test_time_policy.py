import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import esp_client
from shared.time_utils import utc_now
from shared.time_utils import unix_epoch, visible_date_time
from storage import measurements_store as store


class TimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        store.DATA_DIR = root
        store.MEASUREMENTS_DB_FILE = root / 'measurements.sqlite3'

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_utc_and_offset_are_same_instant(self):
        self.assertEqual(
            unix_epoch('2026-07-20T17:46:35Z'),
            unix_epoch('2026-07-20T11:46:35-06:00'),
        )
        self.assertEqual(
            visible_date_time('2026-07-20T17:46:35Z'),
            ('2026-07-20', '11:46:35'),
        )

    def test_midnight_utc_can_be_previous_local_day(self):
        self.assertEqual(
            visible_date_time('2026-07-21T03:00:00Z'),
            ('2026-07-20', '21:00:00'),
        )

    def test_epoch_drift_has_no_false_six_hour_offset(self):
        now_epoch = int(utc_now().timestamp())
        drift = esp_client._time_drift_seconds({'current_epoch': now_epoch})
        self.assertLessEqual(abs(drift), 1)

    @patch('services.esp_client.fetch_json_sync')
    @patch('services.esp_client.post_json_sync')
    def test_server_does_not_overwrite_valid_gps_or_ntp(self, post_json, fetch_json):
        fetch_json.return_value = {
            'ok': True,
            'data': {
                'time_valid': True,
                'needs_time_sync': False,
                'time_source': 'gps',
                'current_epoch': int(utc_now().timestamp()),
            },
        }
        result = esp_client.sync_time_if_needed_sync('ecosensor01.local')
        self.assertTrue(result['ok'])
        self.assertFalse(result['synced'])
        self.assertEqual(result['protected_source'], 'gps')
        post_json.assert_not_called()

    def test_valid_z_is_never_repaired_and_reads_do_not_write(self):
        row = {
            'device_id': 'ecosensor01', 'measurement_id': 1,
            'timestamp': '2026-07-20T17:46:35Z', 'time_valid': True,
            'time_source': 'gps', 'boot_id': 10, 'uptime_s': 300,
            'window_s': 300, 'co2': 500,
        }
        self.assertTrue(store.save_measurement('ecosensor01.local', row))
        db = store.db_file_for_device('ecosensor01')

        def snapshot():
            with sqlite3.connect(db) as conn:
                return conn.execute(
                    'SELECT device_timestamp, time_valid, time_source FROM measurements ORDER BY id'
                ).fetchall()

        before = snapshot()
        self.assertEqual(store.repair_historical_invalid_timestamps('ecosensor01'), 0)
        store.get_latest_measurement('ecosensor01')
        store.graph_rows_all('ecosensor01')
        store.measurements_csv_text('ecosensor01')
        store.validate_measurements_for_csv('ecosensor01')
        self.assertEqual(snapshot(), before)

    def test_parseable_z_is_not_replaced_even_if_legacy_flag_is_false(self):
        row = {
            'device_id': 'ecosensor01', 'measurement_id': 1,
            'timestamp': '2026-07-20T17:46:35Z', 'time_valid': False,
            'time_source': 'uptime', 'boot_id': 10, 'uptime_s': 300,
            'window_s': 300,
        }
        store.save_measurement('ecosensor01.local', row)
        self.assertEqual(store.repair_historical_invalid_timestamps('ecosensor01'), 0)

    def test_invalid_duplicate_does_not_destroy_valid_timestamp(self):
        valid = {
            'device_id': 'ecosensor01', 'measurement_id': 4,
            'timestamp': '2026-07-20T17:46:35Z', 'time_valid': True,
            'time_source': 'gps', 'boot_id': 10, 'uptime_s': 600,
        }
        invalid = {**valid, 'timestamp': '', 'time_valid': False, 'time_source': 'uptime'}
        store.save_measurement('ecosensor01.local', valid)
        store.save_measurement('ecosensor01.local', invalid)
        with sqlite3.connect(store.db_file_for_device('ecosensor01')) as conn:
            timestamp, time_valid, source = conn.execute(
                'SELECT device_timestamp, time_valid, time_source FROM measurements WHERE source_id=4'
            ).fetchone()
        self.assertEqual(timestamp, valid['timestamp'])
        self.assertEqual(time_valid, 1)
        self.assertEqual(source, 'gps')

    def test_only_explicit_invalid_row_is_reconstructed(self):
        rows = [
            {'device_id': 'ecosensor01', 'measurement_id': 1, 'timestamp': '',
             'time_valid': False, 'time_source': 'uptime', 'boot_id': 7,
             'uptime_s': 300, 'window_s': 300},
            {'device_id': 'ecosensor01', 'measurement_id': 2,
             'timestamp': '2026-07-20T17:10:00Z', 'time_valid': True,
             'time_source': 'gps', 'boot_id': 7, 'uptime_s': 600, 'window_s': 300},
        ]
        self.assertEqual(store.save_measurements_bulk('ecosensor01.local', rows, 'ecosensor01'), 2)
        self.assertEqual(store.repair_historical_invalid_timestamps('ecosensor01'), 1)
        with sqlite3.connect(store.db_file_for_device('ecosensor01')) as conn:
            repaired, source, original = conn.execute(
                'SELECT device_timestamp, time_source, original_device_timestamp FROM measurements WHERE source_id=1'
            ).fetchone()
        self.assertEqual(repaired, '2026-07-20T17:05:00Z')
        self.assertEqual(source, store.HISTORICAL_BACKFILLED_SOURCE)
        self.assertIsNone(original)


if __name__ == '__main__':
    unittest.main()
