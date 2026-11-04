"""Cliente HTTP pequeño basado en la biblioteca estándar."""

from __future__ import annotations

import http.client
import json
import secrets
import ssl
from pathlib import Path
from urllib.parse import urlsplit


def _connection(server: str) -> tuple[http.client.HTTPConnection, str]:
    parsed = urlsplit(server)
    prefix = parsed.path.rstrip("/")
    if parsed.scheme == "https":
        connection: http.client.HTTPConnection = http.client.HTTPSConnection(
            parsed.hostname,
            parsed.port,
            timeout=60,
            context=ssl.create_default_context(),
        )
    else:
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=60)
    return connection, prefix


def _error_body(response: http.client.HTTPResponse) -> str:
    body = response.read(4096).decode("utf-8", errors="replace").strip()
    if body:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
                return parsed["error"]
        except json.JSONDecodeError:
            pass
        return body
    return f"HTTP {response.status} {response.reason}"


def upload(server: str, token: str, encrypted_path: Path) -> dict[str, object]:
    connection, prefix = _connection(server)
    endpoint = f"{prefix}/api/v1/transfers"
    size = encrypted_path.stat().st_size
    boundary = "secretbox-" + secrets.token_hex(16)
    file_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="ciphertext"; filename="secretbox.age"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("ascii")
    closing_boundary = f"\r\n--{boundary}--\r\n".encode("ascii")
    content_length = len(file_header) + size + len(closing_boundary)
    try:
        connection.putrequest("POST", endpoint)
        connection.putheader("Authorization", f"Bearer {token}")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(content_length))
        connection.putheader("Connection", "close")
        connection.endheaders()
        connection.send(file_header)
        with encrypted_path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                connection.send(chunk)
        connection.send(closing_boundary)
        response = connection.getresponse()
        body = response.read(8192)
        if response.status != 201:
            raise RuntimeError(_error_body_from_bytes(response.status, response.reason, body))
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("El servidor devolvió una respuesta JSON inválida") from exc
        if not isinstance(data, dict):
            raise RuntimeError("El servidor devolvió una respuesta inválida")
        return data
    except http.client.HTTPException as exc:
        raise RuntimeError(f"Error HTTP al subir: {exc}") from exc
    finally:
        connection.close()


def _error_body_from_bytes(status: int, reason: str, body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    if text:
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("error"), str):
                return data["error"]
        except json.JSONDecodeError:
            pass
        return text
    return f"HTTP {status} {reason}"


def download(server: str, transfer_id: str, destination: Path) -> None:
    connection, prefix = _connection(server)
    endpoint = f"{prefix}/api/v1/transfers/{transfer_id}"
    try:
        connection.request("GET", endpoint, headers={"Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(_error_body(response))
        with destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except http.client.HTTPException as exc:
        raise RuntimeError(f"Error HTTP al descargar: {exc}") from exc
    finally:
        connection.close()


def delete(server: str, token: str, transfer_id: str) -> None:
    connection, prefix = _connection(server)
    endpoint = f"{prefix}/api/v1/transfers/{transfer_id}"
    try:
        connection.request(
            "DELETE",
            endpoint,
            headers={"Authorization": f"Bearer {token}", "Connection": "close"},
        )
        response = connection.getresponse()
        if response.status != 204:
            raise RuntimeError(_error_body(response))
    except http.client.HTTPException as exc:
        raise RuntimeError(f"Error HTTP al borrar: {exc}") from exc
    finally:
        connection.close()

