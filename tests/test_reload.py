import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Path(self.temp.name) / 'config.json'
        self.settings.write_text('{}', encoding='utf-8')
        env = {'APPDATA': self.temp.name, 'KCC_CONFIG_PATH': str(self.settings),
               'KCC_CONFIG_JSON': json.dumps({'instances': [{'name': 'test', 'token': 'stale-dummy'}]})}
        with patch.dict(os.environ, env):
            spec = importlib.util.spec_from_file_location('kcc_test', Path(__file__).parents[1] / 'scripts' / 'kosek_control_center_mcp.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)

    def runtime(self, token):
        return {'instances': [{'name': 'test', 'baseUrl': 'http://ha.invalid',
                                'token': token, 'verifySsl': True}]}

    def result(self, token):
        return subprocess.CompletedProcess([], 0, json.dumps(self.runtime(token)).encode(), b'')

    def call(self, name, args=None):
        reply = self.module.handle({'id': 1, 'method': 'tools/call',
                                    'params': {'name': name, 'arguments': args or {}}})
        return reply['result']

    def change_file(self, text):
        previous = self.settings.stat().st_mtime_ns
        self.settings.write_text(text, encoding='utf-8')
        os.utime(self.settings, ns=(previous + 1000000000, previous + 1000000000))

    def loader(self, **kwargs):
        return patch.object(self.module.subprocess, 'run', **kwargs)

    def test_rotated_token_is_used_without_restart(self):
        with self.loader(side_effect=[self.result('old-dummy'), self.result('new-dummy')]) as run:
            self.module.refresh_config()
            self.change_file('{"changed":true}')
            self.module.refresh_config()
            self.assertEqual(run.call_count, 2)
        with patch.object(self.module.urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = b'{"message":"API running."}'
            request.return_value.__enter__.return_value.headers = {'Content-Type': 'application/json'}
            self.module.api_request(self.module.instance_for({'instance': 'test'}), '/api/')
            self.assertEqual(request.call_args.args[0].get_header('Authorization'), 'Bearer new-dummy')

    def test_unchanged_config_does_not_decrypt_again(self):
        with self.loader(return_value=self.result('valid-dummy')) as run:
            self.module.refresh_config()
            self.module.refresh_config()
            self.assertEqual(run.call_count, 1)

    def test_invalid_settings_fail_closed_and_recover(self):
        bad = subprocess.CompletedProcess([], 1, b'', b'sensitive-dummy-error')
        with self.loader(side_effect=[self.result('old-dummy'), bad, self.result('recovered-dummy')]):
            self.assertFalse(self.call('list_instances')['isError'])
            self.change_file('{broken')
            with patch.object(self.module.urllib.request, 'urlopen') as network:
                reply = self.call('status', {'instance': 'test'})
                self.assertTrue(reply['isError'])
                self.assertNotIn('sensitive-dummy-error', reply['content'][0]['text'])
                network.assert_not_called()
            self.change_file('{"repaired":true}')
            self.assertFalse(self.call('list_instances')['isError'])
            self.assertEqual(self.module.CONFIG['instances'][0]['token'], 'recovered-dummy')

    def test_windows_module_path_is_removed_case_insensitively(self):
        with patch.dict(os.environ, {'PSMODULEPATH': 'incompatible-dummy-path'}):
            with self.loader(return_value=self.result('valid-dummy')) as run:
                self.module.refresh_config()
                self.assertFalse(any(k.upper() == 'PSMODULEPATH' for k in run.call_args.kwargs['env']))
                self.assertNotIn('valid-dummy', ' '.join(run.call_args.args[0]))

    def test_http_401_has_safe_actionable_message(self):
        self.module.CONFIG = self.runtime('secret-dummy')
        denied = urllib.error.HTTPError('http://ha.invalid', 401, 'Unauthorized', {}, None)
        with patch.object(self.module.urllib.request, 'urlopen', side_effect=denied):
            with self.assertRaises(RuntimeError) as caught:
                self.module.api_request(self.module.CONFIG['instances'][0], '/api/')
            self.assertIn('(401)', str(caught.exception))
            self.assertIn('update-token.ps1', str(caught.exception))
            self.assertNotIn('secret-dummy', str(caught.exception))

    def test_network_error_does_not_claim_invalid_token(self):
        self.module.CONFIG = self.runtime('secret-dummy')
        with patch.object(self.module.urllib.request, 'urlopen', side_effect=urllib.error.URLError('secret-dummy')):
            with self.assertRaises(RuntimeError) as caught:
                self.module.api_request(self.module.CONFIG['instances'][0], '/api/')
            self.assertIn('neni dostupny', str(caught.exception))
            self.assertNotIn('secret-dummy', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
