"""Configuración local del CLI."""

from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


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
        raise RuntimeError(f"No se pudo leer la configuración {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"La configuración {path} debe ser un objeto JSON")
    return {key: value for key, value in data.items() if isinstance(value, str)}


def validate_server(server: str) -> str:
    parsed = urlsplit(server)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("La URL debe empezar por http:// o https:// y tener un host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("No incluyas credenciales en la URL del servidor")
    if parsed.query or parsed.fragment:
        raise ValueError("La URL del servidor no debe incluir query ni fragmento")
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
        json.dump(values, handle, indent=2)
        handle.write("\n")
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path


def configure() -> None:
    current = read_config()
    default = current.get("server", "https://secretbox.example.com")
    server = input(f"URL del servidor [{default}]: ").strip() or default
    server = validate_server(server)

    print("Introduce el token de subida que ya configuraste en el servidor.")
    token = getpass.getpass("Token de subida: ")
    if not token:
        raise ValueError("El token no puede estar vacío")
    if len(token.encode("utf-8")) < 32:
        raise ValueError("El token debe tener al menos 32 bytes")

    path = save_config({"server": server, "token": token})
    print(f"Configuración guardada en {path}")

def server_setting(server_override: str | None = None) -> str:
    config = read_config()
    server = server_override or os.environ.get("SECRETBOX_SERVER") or config.get("server")
    if not server:
        raise RuntimeError("Falta la URL del servidor. Ejecuta `sb configure`.")
    return validate_server(server)


def connection_settings(server_override: str | None = None) -> tuple[str, str]:
    config = read_config()
    server = server_setting(server_override)
    token = os.environ.get("SECRETBOX_TOKEN") or config.get("token")
    if not token:
        raise RuntimeError("Falta el token de subida. Ejecuta `sb configure` en un equipo autorizado.")
    return server, token


def identity_dir() -> Path:
    path = config_dir() / "identities"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path

