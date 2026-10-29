import json
import unittest
from unittest.mock import Mock, patch
from contextlib import contextmanager
import test_reload

class FragmentTests(unittest.TestCase):
    setUp = test_reload.ReloadTests.setUp

    def test_fragmented_utf8_with_ping(self):
        ws = self.module.SimpleWebSocket.__new__(self.module.SimpleWebSocket)
        ws.sock = Mock()
        payload = json.dumps({'result': 'příjem'}, ensure_ascii=False).encode('utf-8')
        split = payload.index('ř'.encode('utf-8')) + 1
        a, b = payload[:split], payload[split:]
        ws.buffer = bytes([1, len(a)]) + a + b'\x89\x01x' + bytes([128, len(b)]) + b
        self.assertEqual(ws.receive(), {'result': 'příjem'})
        self.assertEqual(ws.sock.sendall.call_args.args[0][0], 0x8a)
        ws.sock.recv.assert_not_called()

    def test_no_tailscale_route_still_holds_lock(self):
        locked = []
        @contextmanager
        def lock():
            locked.append(True)
            yield
            locked.pop()
        self.module.CONFIG = {'instances': [{'name': 'test', 'token': 'synthetic'}]}
        def request(*args, **kwargs):
            self.assertTrue(locked)
            return {}
        with patch.object(self.module, 'network_lock', lock), \
             patch.object(self.module, 'api_request', request), \
             patch.object(self.module, 'tailscale_cli') as cli:
            self.module.execute_tool('get_state', {'entity_id': 'sensor.test'})
        cli.assert_not_called()
