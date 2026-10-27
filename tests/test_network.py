import unittest
from unittest.mock import patch, call
from contextlib import nullcontext
import test_reload


class NetworkTests(unittest.TestCase):
    setUp = test_reload.ReloadTests.setUp

    def item(self):
        return {'name': 'test', 'baseUrl': 'http://ha.invalid', 'token': 'synthetic',
                'tailscale': {'enabled': True, 'profileId': 'target', 'account': 'test@example.invalid'}}

    def profiles(self, selected='old'):
        return [{'id': 'old', 'account': 'old@example.invalid', 'selected': selected == 'old'},
                {'id': 'target', 'account': 'test@example.invalid', 'selected': selected == 'target'}]

    def test_reachable_shared_device_does_not_switch(self):
        with patch.object(self.module, 'endpoint_reachable', return_value=True), patch.object(self.module, 'tailscale_cli') as cli:
            self.assertEqual(self.module.ensure_network(self.item())['action'], 'kept_current_connection')
            cli.assert_not_called()

    def test_missing_or_mismatched_profile_stops_without_switch(self):
        with patch.object(self.module, 'endpoint_reachable', return_value=False), patch.object(self.module, 'tailscale_cli', return_value=[]) as cli:
            with self.assertRaises(RuntimeError): self.module.ensure_network(self.item())
            self.assertEqual(cli.call_args_list, [call('switch', '--list', '--json')])

    def test_switch_checks_selected_profile_then_reachability(self):
        with patch.object(self.module, 'endpoint_reachable', side_effect=[False, True]), patch.object(self.module, 'tailscale_cli', side_effect=[self.profiles(), None, {'BackendState': 'Running'}, self.profiles('target')]) as cli:
            self.assertEqual(self.module.ensure_network(self.item())['action'], 'switched_profile')
            self.assertIn(call('switch', 'target'), cli.call_args_list)

    def test_login_required_restores_previous_profile(self):
        with patch.object(self.module, 'endpoint_reachable', return_value=False), patch.object(self.module, 'tailscale_cli', side_effect=[self.profiles(), None, {'BackendState': 'NeedsLogin'}, None]) as cli:
            with self.assertRaises(RuntimeError): self.module.ensure_network(self.item())
            self.assertEqual(cli.call_args_list[-1], call('switch', 'old'))

    def test_stopped_profile_is_reconnected(self):
        with patch.object(self.module, 'endpoint_reachable', side_effect=[False, True]), patch.object(self.module, 'tailscale_cli', side_effect=[self.profiles('target'), {'BackendState': 'Stopped'}, None, {'BackendState': 'Running'}, self.profiles('target')]) as cli:
            self.assertEqual(self.module.ensure_network(self.item())['action'], 'reconnected')
            self.assertIn(call('up', '--timeout=15s'), cli.call_args_list)

    def test_network_failure_prevents_service_write(self):
        self.module.CONFIG = {'instances': [self.item()]}
        with patch.object(self.module, 'network_lock', return_value=nullcontext()), patch.object(self.module, 'ensure_network', side_effect=RuntimeError('offline')), patch.object(self.module, 'api_request') as api:
            with self.assertRaises(RuntimeError):
                self.module.execute_tool('call_service', {'instance': 'test', 'domain': 'light', 'service': 'turn_on'})
            api.assert_not_called()

    def test_write_failure_is_never_retried(self):
        self.module.CONFIG = {'instances': [self.item()]}
        with patch.object(self.module, 'network_lock', return_value=nullcontext()), patch.object(self.module, 'ensure_network', return_value={'action': 'kept_current_connection'}), patch.object(self.module, 'api_request', side_effect=TimeoutError('timeout')) as api:
            with self.assertRaises(TimeoutError):
                self.module.execute_tool('call_service', {'instance': 'test', 'domain': 'light', 'service': 'turn_on'})
            api.assert_called_once()

    def test_disabled_route_never_runs_cli(self):
        item = self.item(); item.pop('tailscale')
        with patch.object(self.module, 'tailscale_cli') as cli:
            self.assertEqual(self.module.ensure_network(item)['action'], 'not_configured')
            cli.assert_not_called()
