"""Exercise real PHP commands and requests against temporary token registries."""

import hashlib
import http.client
import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("php"), "PHP is required")
class TokenTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "private" / "server.json"
        self.env = dict(os.environ, SECRETBOX_UPLOAD_TOKEN_FILE=str(self.path),
                        SECRETBOX_UPLOAD_TOKEN="E"*64, SECRETBOX_STORAGE_DIR=str(self.root / "transfers"))

    def command(self, *arguments, success=True):
        result = subprocess.run(["php", str(SERVER / "bin/tokens.php"), *arguments],
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result.stdout

    def token(self, *arguments):
        token = self.command(*arguments).strip().splitlines()[-1]
        self.assertRegex(token, r"^[a-f0-9]{64}$")
        return token

    def accepts(self, token):
        code = "require " + json.dumps(str(SERVER / "src/UploadTokens.php")) + "; "
        code += "echo SecretBox\\UploadTokens::accepts(SecretBox\\UploadTokens::load(), getenv('AUDIT_AUTHORIZATION')) ? 'yes' : 'no';"
        return subprocess.check_output(["php", "-r", code], env=dict(self.env, AUDIT_AUTHORIZATION="Bearer " + token), text=True) == "yes"

    def write(self, config):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.write_text(json.dumps(config))

    def test_independent_add_revoke_and_hashed_storage(self):
        desktop = self.token("init", "desktop")
        laptop = self.token("add", "laptop")
        self.assertTrue(self.accepts(desktop))
        self.assertTrue(self.accepts(laptop))
        self.assertFalse(self.accepts("wrong"*16))
        saved = self.path.read_text()
        self.assertNotIn(desktop, saved)
        self.assertNotIn(laptop, saved)
        listing = self.command("list")
        self.assertIn("desktop\t", listing)
        self.assertNotIn(hashlib.sha256(desktop.encode()).hexdigest(), listing)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.command("revoke", "laptop")
        self.assertFalse(self.accepts(laptop))
        self.assertTrue(self.accepts(desktop))
        self.command("revoke", "desktop")
        self.assertFalse(self.accepts(desktop))
        self.assertFalse(self.accepts(self.env["SECRETBOX_UPLOAD_TOKEN"]))
        self.assertEqual(json.loads(self.path.read_text())["upload_tokens"], {})
        replacement = self.token("add", "replacement")
        self.assertTrue(self.accepts(replacement))

    def test_explicit_legacy_migration_preserves_token(self):
        legacy = "L"*64
        for version in (None, 0, 1):
            with self.subTest(version=version):
                config = {"upload_token": legacy}
                if version is not None:
                    config["schema_version"] = version
                self.write(config)
                self.assertTrue(self.accepts(legacy))
                before = self.path.read_text()
                self.command("add", "laptop", success=False)
                self.assertEqual(self.path.read_text(), before)
                self.command("migrate")
                migrated = self.path.read_text()
                self.command("migrate")
                self.assertEqual(self.path.read_text(), migrated)
                self.assertTrue(self.accepts(legacy))
                updated = json.loads(self.path.read_text())
                self.assertEqual(updated["schema_version"], 2)
                self.assertIn("legacy", updated["upload_tokens"])
                self.assertNotIn(legacy, self.path.read_text())
                self.command("revoke", "legacy")
                self.assertFalse(self.accepts(legacy))

    def test_unknown_invalid_versions_and_records_fail_closed(self):
        for version in (None, True, -1, 3, "2"):
            self.write({"schema_version": version, "upload_token": "L"*64})
            self.command("list", success=False)
            self.command("migrate", success=False)
        self.write({"schema_version": 2, "upload_tokens": {"bad": {"sha256": "wrong", "created_at": "now"}}})
        self.command("list", success=False)

    def test_environment_migration_and_no_missing_file_fallback(self):
        self.command("migrate")
        self.assertTrue(self.accepts(self.env["SECRETBOX_UPLOAD_TOKEN"]))
        self.command("revoke", "legacy")
        self.assertFalse(self.accepts(self.env["SECRETBOX_UPLOAD_TOKEN"]))
        self.path.unlink()
        code = "require " + json.dumps(str(SERVER / "src/UploadTokens.php")) + "; try { SecretBox\\UploadTokens::load(); exit(1); } catch (RuntimeException $e) { exit(0); }"
        subprocess.run(["php", "-r", code], env=self.env, check=True)

    def test_duplicate_invalid_names_and_symlinks(self):
        self.token("init", "desktop")
        before = self.path.read_text()
        for args in (("init", "other"), ("add", "desktop"), ("add", "../escape"), ("revoke", "missing")):
            self.command(*args, success=False)
            self.assertEqual(before, self.path.read_text())
        other = self.root / "other.json"
        self.path.rename(other)
        self.path.symlink_to(other)
        self.command("list", success=False)
        self.assertEqual(other.read_text(), before)

    def test_management_does_not_chmod_a_shared_parent_directory(self):
        self.path.parent.mkdir(mode=0o755)
        self.path.parent.chmod(0o755)
        self.command("init", success=False)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o755)
        self.assertFalse(self.path.exists())

    def test_registry_limit_is_enforced(self):
        self.write({"schema_version": 2, "upload_tokens": {
            "device"+str(i): {"sha256": "a"*64, "created_at": "2026-01-01T00:00:00+00:00"}
            for i in range(100)
        }})
        before = self.path.read_text()
        self.command("add", "overflow", success=False)
        self.assertEqual(self.path.read_text(), before)

    def test_concurrent_additions_do_not_lose_updates(self):
        self.token("init", "desktop")
        processes = [subprocess.Popen(["php", str(SERVER / "bin/tokens.php"), "add", "device"+letter],
                                     env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for letter in "abcdefgh"]
        for process in processes:
            _, errors = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(len(json.loads(self.path.read_text())["upload_tokens"]), 9)

    def test_first_setup_writes_only_the_initial_token_hash(self):
        site = self.root / "site"
        (site / "bin").mkdir(parents=True)
        home = self.root / "home"
        home.mkdir()
        script = site / "bin/configure.php"
        shutil.copyfile(SERVER / "bin/configure.php", script)
        env = dict(self.env, HOME=str(home), SECRETBOX_UPLOAD_TOKEN="", SECRETBOX_UPLOAD_TOKEN_FILE="")
        result = subprocess.run(["php", str(script)], env=env, text=True, capture_output=True, check=True)
        token = next(line for line in result.stdout.splitlines() if len(line) == 64 and all(c in "0123456789abcdef" for c in line))
        generated = home / ".config/secretbox/server.json"
        document = json.loads(generated.read_text())
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(document["upload_tokens"]["default"]["sha256"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, generated.read_text())
        self.assertEqual(stat.S_IMODE(generated.stat().st_mode), 0o600)
        before = generated.read_text()
        second = subprocess.run(["php", str(script)], env=env, text=True, capture_output=True)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(generated.read_text(), before)

    def test_live_api_revocation_and_unauthenticated_download(self):
        desktop = self.token("init", "desktop")
        laptop = self.token("add", "laptop")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen(["php", "-S", f"127.0.0.1:{port}", "-t", str(SERVER / "public"), str(SERVER / "public/index.php")],
                                   env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def request(method, path, token=None, body=None):
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            headers = {"Content-Type": "application/octet-stream"}
            if token:
                headers["Authorization"] = "Bearer " + token
            try:
                connection.request(method, path, body, headers)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()
        try:
            for _ in range(50):
                try:
                    if request("GET", "/healthz")[0] == 200:
                        break
                except OSError:
                    pass
                time.sleep(.02)
            for token in (desktop, laptop):
                status, response = request("POST", "/api/v1/transfers", token, b"dummy ciphertext")
                self.assertEqual(status, 201, response)
            transfer = json.loads(response)["id"]
            self.command("revoke", "laptop")
            self.assertEqual(request("POST", "/api/v1/transfers", laptop, b"dummy")[0], 401)
            self.assertEqual(request("DELETE", "/api/v1/transfers/"+transfer, laptop)[0], 401)
            self.assertEqual(request("GET", "/api/v1/transfers/"+transfer), (200, b"dummy ciphertext"))
            self.assertEqual(request("DELETE", "/api/v1/transfers/"+transfer, desktop)[0], 204)
            self.command("revoke", "desktop")
            self.assertEqual(json.loads(request("GET", "/")[1]), {"ok": False})
            self.assertEqual(request("POST", "/api/v1/transfers", desktop, b"dummy")[0], 503)
        finally:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
