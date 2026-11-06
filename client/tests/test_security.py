"""Regression checks for credential, filesystem, and resource boundaries."""

import io
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from secretbox import age, api, bundle, config


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "SECRETBOX_SERVER": "", "SECRETBOX_TOKEN": "",
            "SECRETBOX_ALLOW_HTTP_LOOPBACK": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_https_and_explicit_loopback_exception(self):
        for url in ("http://remote.example", "http://localhost", "http://127.0.0.1"):
            with self.assertRaises(ValueError):
                config.validate_server(url)
        with patch.dict(os.environ, {"SECRETBOX_ALLOW_HTTP_LOOPBACK": "1"}):
            self.assertEqual(config.validate_server("http://127.0.0.1"), "http://127.0.0.1")
            with self.assertRaises(ValueError):
                config.validate_server("http://remote.example")

    def test_credentials_are_scoped_to_endpoint(self):
        config.save_config({"server": "https://trusted.example/box", "token": "dummy-token"})
        self.assertEqual(config.connection_settings("https://TRUSTED.example:443/box/")[1], "dummy-token")
        for server in ("https://other.example/box", "https://trusted.example/other", "https://trusted.example:444/box"):
            with self.assertRaises(RuntimeError):
                config.connection_settings(server)
            with patch.dict(os.environ, {"SECRETBOX_SERVER": server}):
                with self.assertRaises(RuntimeError):
                    config.connection_settings()
        with patch.dict(os.environ, {"SECRETBOX_TOKEN": "explicit-destination-token"}):
            self.assertEqual(config.connection_settings("https://other.example")[1], "explicit-destination-token")

    def make_bundle(self):
        path = self.root / "bundle.tar.gz"
        with path.open("wb") as output:
            bundle.write_bundle(output, text=b"dummy secret")
        return path

    def test_plaintext_publication_stays_on_destination_filesystem(self):
        target = self.root / "destination" / "text.txt"
        real_link = os.link
        def inspect_link(source, destination):
            self.assertEqual(source.parent.parent.parent, target.parent)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(source.parent.parent.stat().st_mode), 0o700)
            real_link(source, destination)
        old_umask = os.umask(0o022)
        try:
            with patch.object(bundle.os, "link", side_effect=inspect_link):
                bundle.extract_bundle(self.make_bundle(), target)
        finally:
            os.umask(old_umask)
        self.assertEqual(target.read_bytes(), b"dummy secret")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_existing_destination_is_not_replaced(self):
        target = self.root / "existing"
        target.write_text("keep")
        with self.assertRaises(FileExistsError):
            bundle.extract_bundle(self.make_bundle(), target)
        self.assertEqual(target.read_text(), "keep")

    def test_text_limit(self):
        with patch.object(bundle, "MAX_TEXT_BYTES", 4), self.assertRaises(ValueError):
            bundle.extract_bundle(self.make_bundle(), self.root / "output")
        self.assertFalse((self.root / "output").exists())

    def test_download_limits_and_truncation(self):
        class Response:
            status = 200
            def __init__(self, data, declared):
                self.stream = io.BytesIO(data)
                self.declared = declared
            def getheader(self, name): return self.declared
            def read1(self, size): return self.stream.read(size)
        class Connection:
            sock = None
            def connect(self): pass
            def request(self, *args, **kwargs): pass
            def close(self): pass
        for index, (data, declared) in enumerate(((b"x"*20, None), (b"x", "20"), (b"x", "4"))):
            connection = Connection()
            connection.getresponse = lambda: Response(data, declared)
            destination = self.root / f"download-{index}"
            with patch.object(api, "MAX_CIPHERTEXT_BYTES", 8), patch.object(api, "_connection", return_value=(connection, "")):
                with self.assertRaises(RuntimeError):
                    api.download("https://dummy.example", "A"*32, destination)
            self.assertLessEqual(destination.stat().st_size if destination.exists() else 0, 8)

    def test_download_deadline_interrupts_a_stalled_body(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        release = threading.Event()
        def stalled_peer():
            with server:
                peer, _ = server.accept()
                with peer:
                    peer.recv(4096)
                    peer.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\n")
                    release.wait(2)
        thread = threading.Thread(target=stalled_peer, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            with patch.dict(os.environ, {"SECRETBOX_ALLOW_HTTP_LOOPBACK": "1"}), patch.object(api, "TRANSFER_TIMEOUT_SECONDS", .1):
                with self.assertRaises((RuntimeError, OSError)):
                    api.download(f"http://127.0.0.1:{server.getsockname()[1]}", "A"*32, self.root / "stalled")
            self.assertLess(time.monotonic() - started, 1)
        finally:
            release.set()
            thread.join(2)

    def test_decryption_deadline_terminates_the_child(self):
        executable = self.root / "slow-age"
        executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
        executable.chmod(0o700)
        started = time.monotonic()
        with patch.object(age, "_binary", return_value=str(executable)), patch.object(age, "TRANSFER_TIMEOUT_SECONDS", .1):
            with self.assertRaises(RuntimeError):
                age.decrypt_bundle(self.root / "unused", self.root / "stalled-decrypt", [])
        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse((self.root / "stalled-decrypt").exists())

    @unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "age is required")
    def test_real_age_decryption_and_output_limit(self):
        identity = self.root / "identity"
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
        recipient = subprocess.check_output(["age-keygen", "-y", str(identity)], text=True).strip()
        encrypted = self.root / "ciphertext"
        source = self.make_bundle()
        subprocess.run(["age", "-r", recipient, "-o", str(encrypted), str(source)], check=True)
        output = self.root / "decrypted"
        age.decrypt_bundle(encrypted, output, [identity])
        self.assertEqual(source.read_bytes(), output.read_bytes())
        with patch.object(age, "MAX_BUNDLE_BYTES", 8), self.assertRaises(RuntimeError):
            age.decrypt_bundle(encrypted, self.root / "too-large", [identity])
        self.assertFalse((self.root / "too-large").exists())


if __name__ == "__main__":
    unittest.main()
