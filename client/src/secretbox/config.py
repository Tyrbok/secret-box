"""Local CLI configuration."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


CONFIG_SCHEMA_VERSION = 1
SUPPORTED_CONFIG_SCHEMA_VERSIONS = {0, CONFIG_SCHEMA_VERSION}


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "secretbox"


def config_path() -> Path:
    return config_dir() / "config.json"


def read_config() -> dict[str, str]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read configuration at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Configuration at {path} must be a JSON object")
    schema_version = data.get("schema_version", 0)
    if type(schema_version) is not int or schema_version not in SUPPORTED_CONFIG_SCHEMA_VERSIONS:
        raise RuntimeError(
            f"Unsupported configuration schema version in {path}: {schema_version!r}"
        )
    return {key: value for key, value in data.items() if isinstance(value, str)}


def validate_server(server: str) -> str:
    parsed = urlsplit(server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must start with http:// or https:// and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Do not include credentials in the server URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Server URL must not include a query or fragment")
    return server.rstrip("/")


def save_config(values: dict[str, str]) -> Path:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    path = config_path()
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".config-", delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump({**values, "schema_version": CONFIG_SCHEMA_VERSION}, handle, indent=2)
        handle.write("\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path


def configure() -> None:
    current = read_config()
    default = current.get("server", "https://secretbox.example.com")
    server = input(f"Server URL [{default}]: ").strip() or default
    server = validate_server(server)

    print("Enter the upload token already configured on the server.")
    token = getpass.getpass("Upload token: ")
    if not token:
        raise ValueError("Token must not be empty")
    if len(token.encode("utf-8")) < 32:
        raise ValueError("Token must contain at least 32 bytes")

    path = save_config({"server": server, "token": token})
    print(f"Configuration saved to {path}")

def server_setting(server_override: str | None = None) -> str:
    config = read_config()
    server = server_override or os.environ.get("SECRETBOX_SERVER") or config.get("server")
    if not server:
        raise RuntimeError("Server URL is missing. Run sb configure.")
    return validate_server(server)


def connection_settings(server_override: str | None = None) -> tuple[str, str]:
    config = read_config()
    server = server_setting(server_override)
    token = os.environ.get("SECRETBOX_TOKEN") or config.get("token")
    if not token:
        raise RuntimeError("Upload token is missing. Run sb configure on an authorized device.")
    return server, token


def identity_dir() -> Path:
    path = config_dir() / "identities"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path

