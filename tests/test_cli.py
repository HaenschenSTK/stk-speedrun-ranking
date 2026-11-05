"""Offline checks for multi-track command orchestration."""
import contextlib
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from stk_rankings.__main__ import main


class SyncCommandTests(unittest.TestCase):
    def invoke(self, arguments, side_effect=None):
        output, errors = io.StringIO(), io.StringIO()
        db, api = MagicMock(), MagicMock()
        config = {'tracks': {'official': {}, 'bonus': {'bonus': True}}}
        with patch('sys.argv', ['stk-rankings', 'sync', *arguments]), \
             patch('stk_rankings.__main__.connect', return_value=db), \
             patch('stk_rankings.__main__.Api', return_value=api), \
             patch('stk_rankings.__main__.tomllib.loads', return_value=config), \
             patch('stk_rankings.__main__.sync', side_effect=side_effect or [{'track': 'official'}, {'track': 'bonus'}]) as sync, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            exit_code = None
            try:
                main()
            except SystemExit as error:
                exit_code = error.code
        return output.getvalue(), errors.getvalue(), sync, db, api, exit_code

    def test_all_tracks_share_client_and_full_flag(self):
        output, errors, sync, db, api, code = self.invoke(['--all', '--full'])
        self.assertIsNone(code)
        self.assertEqual(json.loads(output), [{'track': 'official'}, {'track': 'bonus'}])
        self.assertEqual([call.args[3:] for call in sync.call_args_list], [('official', True), ('bonus', True)])
        self.assertTrue(all(call.args[1] is api for call in sync.call_args_list))
        self.assertIn('[2/2] Syncing bonus', errors)
        db.close.assert_called_once()

    def test_incremental_and_single_track(self):
        output, _, sync, _, _, _ = self.invoke(['--track', 'official'])
        self.assertEqual(json.loads(output), {'track': 'official'})
        self.assertEqual(sync.call_args.args[3:], ('official', False))
        _, _, sync, _, _, _ = self.invoke(['--all'])
        self.assertTrue(all(call.args[4] is False for call in sync.call_args_list))

    def test_failure_stops_and_closes_database(self):
        output, errors, sync, db, _, code = self.invoke(['--all'], [OSError('network unavailable')])
        self.assertEqual(code, 1)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(output, '')
        self.assertIn('Sync failed for official', errors)
        db.close.assert_called_once()

    def test_all_and_track_are_mutually_exclusive(self):
        _, _, sync, _, _, code = self.invoke(['--all', '--track', 'official'])
        self.assertEqual(code, 2)
        sync.assert_not_called()
