"""Integration with age and age-keygen."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import BinaryIO

from .bundle import write_bundle


def _binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(
            f"Could not find {name} on PATH. Install age with brew install age on macOS, "
            "or follow the instructions for your system at https://age-encryption.org/install."
        )
    return path


def encrypt_bundle(
    encrypted_path: Path,
    *,
    source: Path | None = None,
    text: bytes | None = None,
    recipient: str | None = None,
) -> None:
    age = _binary("age")
    command = [age, "--encrypt"]
    if recipient:
        command.extend(["--recipient", recipient])
    else:
        command.append("--passphrase")
    command.extend(["--output", str(encrypted_path), "-"])
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    try:
        write_bundle(process.stdin, source=source, text=text)
        process.stdin.close()
        status = process.wait()
        if status != 0:
            raise RuntimeError(f"age exited with status {status}")
    except BaseException:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            process.wait()
        raise


def decrypt_bundle(encrypted_path: Path, bundle_path: Path, identities: list[Path]) -> None:
    age = _binary("age")
    command = [age, "--decrypt"]
    for identity in identities:
        command.extend(["--identity", str(identity.expanduser())])
    command.extend(["--output", str(bundle_path), str(encrypted_path)])
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"age exited with status {result.returncode}")


def generate_identity(name: str, identities_dir: Path) -> tuple[Path, str]:
    keygen = _binary("age-keygen")
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in name):
        raise ValueError("Name may contain only letters, numbers, hyphens, and underscores")
    identities_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = identities_dir / f"{name}.txt"
    if path.exists():
        raise FileExistsError(f"La identidad ya existe: {path}")
    previous_umask = os.umask(0o077)
    try:
        result = subprocess.run([keygen, "--output", str(path)], check=False)
    finally:
        os.umask(previous_umask)
    if result.returncode != 0:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"age-keygen exited with status {result.returncode}")
    os.chmod(path, 0o600)
    public_result = subprocess.run(
        [keygen, "-y", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if public_result.returncode != 0:
        path.unlink(missing_ok=True)
        raise RuntimeError("Could not read the identity's public key")
    recipient = public_result.stdout.strip()
    if not recipient.startswith("age1"):
        path.unlink(missing_ok=True)
        raise RuntimeError("age-keygen returned an unexpected public key")
    return path, recipient

