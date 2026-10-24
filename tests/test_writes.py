import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = {'instances': [{'name': 'test', 'baseUrl': 'http://ha.invalid',
                                 'token': 'synthetic-dummy'}],
                  'localBackupRoot': self.temp.name}
        with patch.dict(os.environ, {'APPDATA': self.temp.name,
                                    'KCC_CONFIG_JSON': json.dumps(config)}):
            spec = importlib.util.spec_from_file_location(
                'kcc_writes', Path(__file__).parents[1] / 'scripts' / 'kosek_control_center_mcp.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.current = {'views': [{'path': 'home', 'cards': []}]}
        self.proposed = {'views': [{'path': 'home', 'cards': [{'type': 'markdown', 'content': 'Test'}]}]}
        self.args = {'instance': 'test', 'url_path': 'dashboard-test',
                     'config': self.proposed,
                     'expected_current_sha256': self.module.json_sha(self.current)}

    def dispatch(self, name, args):
        with patch.object(self.module, 'refresh_config'):
            response = self.module.handle({'id': 1, 'method': 'tools/call',
                                          'params': {'name': name, 'arguments': args}})
        result = response['result']
        self.assertFalse(result['isError'], result)
        return json.loads(result['content'][0]['text'])

    def test_direct_save_backs_up_before_write_and_reads_back(self):
        def write(item, command):
            backups = list(Path(self.temp.name).rglob('*-before-*.json'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text(encoding='utf-8')), self.current)
            self.assertEqual(command, {'type': 'lovelace/config/save',
                                      'url_path': 'dashboard-test', 'config': self.proposed})
        with patch.object(self.module, 'dashboard_config',
                          side_effect=[self.current, self.current, self.proposed]) as read:
            with patch.object(self.module, 'websocket_command', side_effect=write) as save:
                result = self.dispatch('save_dashboard', self.args)
        self.assertEqual(result['status'], 'saved_and_verified')
        self.assertEqual(result['actual_sha256'], self.module.json_sha(self.proposed))
        self.assertEqual(read.call_count, 3)
        save.assert_called_once()
        self.assertFalse(self.module.PENDING)

    def test_direct_save_requires_expected_hash(self):
        for missing in (None, ''):
            args = dict(self.args)
            if missing is None:
                args.pop('expected_current_sha256')
            else:
                args['expected_current_sha256'] = missing
            with patch.object(self.module, 'dashboard_config') as read:
                with self.assertRaises(ValueError):
                    self.module.save_dashboard(args)
                read.assert_not_called()

    def test_stale_expected_hash_never_writes(self):
        with patch.object(self.module, 'dashboard_config', return_value={'views': []}):
            with patch.object(self.module, 'websocket_command') as save:
                with self.assertRaises(RuntimeError):
                    self.module.save_dashboard(self.args)
                save.assert_not_called()
        self.assertFalse(list(Path(self.temp.name).rglob('*-before-*.json')))

    def test_concurrent_change_after_backup_never_writes(self):
        with patch.object(self.module, 'dashboard_config',
                          side_effect=[self.current, {'views': []}]):
            with patch.object(self.module, 'websocket_command') as save:
                with self.assertRaises(RuntimeError):
                    self.module.save_dashboard(self.args)
                save.assert_not_called()
        self.assertEqual(len(list(Path(self.temp.name).rglob('*-before-*.json'))), 1)
        self.assertFalse(self.module.PENDING)

    def test_mismatch_is_reported_without_retrying_write(self):
        with patch.object(self.module, 'dashboard_config',
                          side_effect=[self.current, self.current, self.current]):
            with patch.object(self.module, 'websocket_command') as save:
                result = self.module.save_dashboard(self.args)
                save.assert_called_once()
        self.assertEqual(result['status'], 'saved_but_verification_mismatch')

    def test_failed_service_is_not_retried(self):
        with patch.object(self.module, 'api_request', side_effect=TimeoutError('synthetic timeout')) as api:
            with self.assertRaises(TimeoutError):
                self.module.call_service({'domain': 'light', 'service': 'turn_on',
                                          'service_data': {'entity_id': 'light.test'}})
            api.assert_called_once()
        self.assertFalse(self.module.PENDING)

    def test_direct_service_dispatches_exact_payload_once(self):
        payload = {'entity_id': 'light.test', 'brightness': 75}
        with patch.object(self.module, 'api_request', return_value=[]) as api:
            result = self.dispatch('call_service', {'domain': 'light', 'service': 'turn_on',
                                                    'service_data': payload})
            api.assert_called_once_with(self.module.CONFIG['instances'][0],
                                        '/api/services/light/turn_on', 'POST', payload)
        self.assertEqual(result['status'], 'called')
        self.assertFalse(self.module.PENDING)

    def test_optional_prepare_does_not_write_and_legacy_commit_works(self):
        with patch.object(self.module, 'dashboard_config', return_value=self.current):
            with patch.object(self.module, 'websocket_command') as save:
                prepared = self.module.prepare_dashboard_save(self.args)
                save.assert_not_called()
        with patch.object(self.module, 'dashboard_config', side_effect=[self.current, self.proposed]):
            with patch.object(self.module, 'websocket_command') as save:
                result = self.module.confirm_dashboard_save({'confirmation_code': prepared['confirmation_code']})
                save.assert_called_once()
        self.assertEqual(result['status'], 'saved_and_verified')


if __name__ == '__main__':
    unittest.main()
