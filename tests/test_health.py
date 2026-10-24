import base64
import hashlib
import json
import ssl
import unittest
import urllib.error
from unittest.mock import patch
import test_reload


class HealthTests(unittest.TestCase):
    setUp = test_reload.ReloadTests.setUp
    runtime = test_reload.ReloadTests.runtime
    def jwt(self, exp):
        part = base64.urlsafe_b64encode(json.dumps({'exp': exp, 'private': 'not-for-output'}).encode()).decode().rstrip('=')
        return 'header.' + part + '.signature'

    def test_expiry_boundaries_and_redaction(self):
        for delta, state in [(-1, 'expired'), (0, 'expired'), (60, 'expiring_soon'), (91*86400, 'valid_by_date')]:
            result = self.module.token_metadata(self.jwt(100000 + delta), now=100000)
            self.assertEqual(result['expiry_state'], state)
            self.assertNotIn('not-for-output', json.dumps(result))
        for value in ['', 'a.b.c', 'a.e30.c', self.jwt('bad'), self.jwt(True)]:
            self.assertEqual(self.module.token_metadata(value)['expiry_state'], 'unknown')

    def test_live_rejection_not_reported_as_expiry(self):
        self.module.CONFIG = self.runtime(self.jwt(4102444800))
        denied = urllib.error.HTTPError('http://ha.invalid', 401, 'secret-error', {}, None)
        with patch.object(self.module.urllib.request, 'urlopen', side_effect=denied):
            result = self.module.connection_health({'instance':'test'})
        self.assertEqual(result['status'], 'auth_rejected')
        self.assertIn('dosud neuplynulo', result['message'])
        self.assertNotIn('secret-error', json.dumps(result))

    def test_tls_failure_is_distinct(self):
        self.module.CONFIG = self.runtime('dummy')
        with patch.object(self.module.urllib.request, 'urlopen', side_effect=urllib.error.URLError(ssl.SSLCertVerificationError('secret'))):
            result = self.module.connection_health({'instance':'test'})
        self.assertEqual(result['status'], 'tls_error')
        self.assertNotIn('secret', json.dumps(result))

    def test_websocket_retains_first_frame_in_handshake_packet(self):
        frame = b'\x81\x18' + b'{"type":"auth_required"}'
        class Socket:
            def settimeout(self, _): pass
            def sendall(self, request):
                key = request.split(b'Sec-WebSocket-Key: ')[1].split(b'\r\n')[0]
                accept = base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                self.response = b'HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n'+frame
            def recv(self, _):
                response, self.response = self.response, b''
                return response
            def close(self): pass
        with patch.object(self.module.socket, 'create_connection', return_value=Socket()):
            ws = self.module.SimpleWebSocket({'baseUrl':'http://ha.invalid'})
            self.assertEqual(ws.receive(), {'type':'auth_required'})

    def test_handshake_eof_stops(self):
        from unittest.mock import Mock
        sock = Mock()
        sock.recv.return_value = b''
        with patch.object(self.module.socket, 'create_connection', return_value=sock):
            with self.assertRaises(RuntimeError):
                self.module.SimpleWebSocket({'baseUrl':'http://ha.invalid'})
        sock.close.assert_called_once()
