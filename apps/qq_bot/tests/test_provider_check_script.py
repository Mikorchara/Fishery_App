"""Local batch driver checks use memory SDK HTTP, never credentials or QQ."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from apps.qq_bot.tests import test_management_live as fixture
from scripts.dev import check_qq_provider as driver


class ProviderCheckTests(unittest.TestCase):
    setUp = fixture.ManagementLiveTests.setUp
    factory = fixture.ManagementLiveTests.factory

    def test_check_does_not_open_sqlite_credentials_or_network(self):
        with patch('sqlite3.connect', side_effect=AssertionError('no SQLite')), \
             patch('apps.ai_backend.credentials.CredentialStore.status', side_effect=AssertionError('no key')), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver.main([]), 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['max_http_requests'], 12)
        self.assertEqual(value['qq_network_requests'], 0)

    def test_two_local_water_turns_no_qq_or_success_history(self):
        self.mode = 'water'
        directory = self.root/'batch'; directory.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            report = driver.execute_batch(self.request, directory, ['当前水质', '溶解氧是多少'], factory=self.factory)
        self.assertEqual(len(self.http), 4)
        self.assertEqual(len(report['cases']), 2)
        self.assertTrue(all(row['contract_valid'] for row in report['cases']))
        self.assertTrue(all(row['tool_executions'] == 1 for row in report['cases']))
        self.assertEqual(report['qq_network_requests'], 0)
        for turn in report['turns']:
            self.assertFalse(turn['verified'])  # Local inspection is NOT QQ acceptance.
            self.assertFalse(turn['outcome']['api_accepted'])
            self.assertEqual(turn['sdk_resources']['state'], 'CLOSED')
            self.assertTrue(turn['sdk_resources']['thread_exited'])
        self.assertTrue((directory/'result.json').is_file())

    def test_invalid_model_arguments_stop_batch_no_retry(self):
        self.mode = 'wrong_device'
        directory = self.root/'batch'; directory.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            report = driver.execute_batch(self.request, directory, ['当前水质', '第二题'], factory=self.factory)
        self.assertEqual(len(self.http), 1)
        self.assertEqual(report['cases'][0]['code'], 'INVALID_TOOL_ARGUMENTS')
        self.assertEqual(len(report['cases']), 1)
        self.assertEqual(report['code'], 'BATCH_FAILED_STOP')

    def test_declined_approval_never_reads_credentials(self):
        with patch('builtins.input', return_value=''), \
             patch('apps.ai_backend.credentials.CredentialStore.status', side_effect=AssertionError('no key')), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, 'PROVIDER_BATCH_DECLINED'):
                driver.main(['--run'])
