"""Exercise discovery through the Python client and a real PHP API."""

import http.client
import io
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from secretbox import api, cli

SERVER = Path(__file__).resolve().parents[2] / 'server'


@unittest.skipUnless(shutil.which('php'), 'PHP is required')
class ListingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.storage = self.root / 'transfers'
        self.token = 'T' * 64
        config = self.root / 'server.json'
        config.write_text(json.dumps({'schema_version': 1, 'upload_token': self.token}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.server = f'http://127.0.0.1:{self.port}'
        env = dict(os.environ, SECRETBOX_STORAGE_DIR=str(self.storage),
                   SECRETBOX_UPLOAD_TOKEN_FILE=str(config))
        process = subprocess.Popen(['php', '-S', f'127.0.0.1:{self.port}', '-t',
                                    str(SERVER / 'public'), str(SERVER / 'public/index.php')],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            process.terminate()
            process.wait(timeout=5)
        self.addCleanup(stop)
        self.environment = patch.dict(os.environ, {
            'SECRETBOX_ALLOW_HTTP_LOOPBACK': '1', 'SECRETBOX_TOKEN': '',
            'SECRETBOX_SERVER': self.server, 'XDG_CONFIG_HOME': str(self.root / 'config'),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for _ in range(100):
            try:
                if self.request('GET', '/healthz')[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(.02)
        else:
            self.fail('PHP did not start')
        self.ciphertext = self.root / 'private-original-name.age'
        self.ciphertext.write_bytes(b'dummy ciphertext')

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_opt_in_listing_and_legacy_downloads(self):
        hidden = api.upload(self.server, self.token, self.ciphertext)
        listed = api.upload(self.server, self.token, self.ciphertext, listable=True)
        self.assertFalse(hidden['listable'])
        self.assertTrue(listed['listable'])
        page = api.list_transfers(self.server)
        self.assertEqual(page, {'transfers': [listed], 'next_cursor': None})
        status, body, headers = self.request('GET', '/api/v1/transfers')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn(b'private-original-name', body)
        self.assertNotIn(b'expires_epoch', body)
        for transfer in (hidden, listed):
            target = self.root / transfer['id']
            api.download(self.server, transfer['id'], target)
            self.assertEqual(target.read_bytes(), self.ciphertext.read_bytes())
        with patch('sys.argv', ['sb', 'list']), redirect_stdout(io.StringIO()) as output:
            cli.main()
        self.assertIn(listed['id'], output.getvalue())
        self.assertNotIn(hidden['id'], output.getvalue())
        metadata_path = self.storage / (listed['id'] + '.json')
        metadata = json.loads(metadata_path.read_text())
        del metadata['listable']
        metadata_path.write_text(json.dumps(metadata))
        self.assertEqual(api.list_transfers(self.server)['transfers'], [])
        metadata['listable'] = 'true'
        metadata_path.write_text(json.dumps(metadata))
        self.assertEqual(api.list_transfers(self.server)['transfers'], [])

    def test_expired_missing_and_deleted_transfers_disappear(self):
        for action in ('expire', 'remove', 'delete'):
            transfer = api.upload(self.server, self.token, self.ciphertext, listable=True)
            if action == 'expire':
                path = self.storage / (transfer['id'] + '.json')
                metadata = json.loads(path.read_text())
                metadata['expires_epoch'] = 0
                path.write_text(json.dumps(metadata))
            elif action == 'remove':
                (self.storage / (transfer['id'] + '.age')).unlink()
            else:
                api.delete(self.server, self.token, transfer['id'])
            self.assertEqual(api.list_transfers(self.server)['transfers'], [])

    def test_pagination_and_invalid_cursors(self):
        seed = api.upload(self.server, self.token, self.ciphertext, listable=True)
        metadata = json.loads((self.storage / (seed['id'] + '.json')).read_text())
        for index in range(102):
            transfer_id = f'{index:032d}'
            (self.storage / (transfer_id + '.age')).write_bytes(b'x')
            (self.storage / (transfer_id + '.json')).write_text(json.dumps(dict(metadata, id=transfer_id)))
        first = api.list_transfers(self.server)
        second = api.list_transfers(self.server, first['next_cursor'])
        ids = [row['id'] for page in (first, second) for row in page['transfers']]
        self.assertEqual(len(first['transfers']), 100)
        self.assertEqual(len(ids), 103)
        self.assertEqual(ids, sorted(set(ids)))
        self.assertIsNone(second['next_cursor'])
        for query in ('after=../escape', 'after[]=bad', 'after=short', 'after=' + 'A' * 32 + '%0A'):
            self.assertEqual(self.request('GET', '/api/v1/transfers?' + query)[0], 400)

    def test_bad_visibility_and_missing_auth_do_not_publish(self):
        def body(value):
            return (b'--test\r\nContent-Disposition: form-data; name="' + value +
                    b'"\r\n\r\ntrue\r\n--test--\r\n')
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Content-Type': 'multipart/form-data; boundary=test'}
        self.assertEqual(self.request('POST', '/api/v1/transfers', body(b'listable[]'), headers)[0], 400)
        with self.assertRaises(RuntimeError):
            api.upload(self.server, 'invalid', self.ciphertext, listable=True)
        status, response, _ = self.request('POST', '/api/v1/transfers', b'raw ciphertext',
                                          {'Authorization': 'Bearer ' + self.token,
                                           'Content-Type': 'application/octet-stream'})
        self.assertEqual(status, 201)
        self.assertFalse(json.loads(response)['listable'])
        self.assertEqual(api.list_transfers(self.server)['transfers'], [])


class ListingResponseTests(unittest.TestCase):
    def test_public_client_omits_credentials_and_bounds_response(self):
        from unittest.mock import Mock
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"transfers": [], "next_cursor": null}'
        with patch.object(api, '_connection', return_value=(connection, '/box')):
            self.assertEqual(api.list_transfers('https://example.com/box')['transfers'], [])
            connection.request.assert_called_once_with(
                'GET', '/box/api/v1/transfers', headers={'Connection': 'close'})
            response.read.return_value = b'x' * 65537
            with self.assertRaises(RuntimeError):
                api.list_transfers('https://example.com/box')
            response.read.return_value = b'{"transfers": "bad"}'
            with self.assertRaises(RuntimeError):
                api.list_transfers('https://example.com/box')

    def test_cli_rejects_terminal_escape_sequences(self):
        row = {'id': 'A' * 32, 'size': 1, 'created_at': '\x1b[31m',
               'expires_at': '2026-01-01T00:00:00+00:00'}
        with patch.object(cli, 'list_transfers', return_value={'transfers': [row]}), \
                patch.object(cli, 'server_setting', return_value='https://example.com'), \
                redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(RuntimeError):
                cli._list(cli._parser().parse_args(['list']))
        self.assertEqual(output.getvalue(), '')
