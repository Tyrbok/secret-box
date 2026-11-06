"""Small HTTP client based on the Python standard library."""

from __future__ import annotations

import http.client
import json
import secrets
import ssl
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from .config import validate_server
from .limits import MAX_CIPHERTEXT_BYTES, TRANSFER_TIMEOUT_SECONDS


def _connection(server: str) -> tuple[http.client.HTTPConnection, str]:
    parsed = urlsplit(validate_server(server))
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


def upload(server: str, token: str, encrypted_path: Path, *, listable: bool = False) -> dict[str, object]:
    connection, prefix = _connection(server)
    endpoint = f"{prefix}/api/v1/transfers"
    size = encrypted_path.stat().st_size
    if size > MAX_CIPHERTEXT_BYTES:
        connection.close()
        raise ValueError("Ciphertext exceeds the client's 100 MiB limit")
    boundary = "secretbox-" + secrets.token_hex(16)
    visibility_field = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="listable"\r\n\r\n'
        f"{'true' if listable else 'false'}\r\n"
    ).encode("ascii")
    file_header = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="ciphertext"; filename="secretbox.age"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("ascii")
    closing_boundary = f"\r\n--{boundary}--\r\n".encode("ascii")
    content_length = len(visibility_field) + len(file_header) + size + len(closing_boundary)
    try:
        connection.putrequest("POST", endpoint)
        connection.putheader("Authorization", f"Bearer {token}")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(content_length))
        connection.putheader("Connection", "close")
        connection.endheaders()
        connection.send(visibility_field)
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
            raise RuntimeError("The server returned an invalid JSON response") from exc
        if not isinstance(data, dict):
            raise RuntimeError("The server returned an invalid response")
        return data
    except http.client.HTTPException as exc:
        raise RuntimeError(f"HTTP upload error: {exc}") from exc
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
    watchdog = None
    started = time.monotonic()
    try:
        connection.connect()
        transport = connection.sock
        def interrupt() -> None:
            if transport is not None:
                try:
                    transport.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        watchdog = threading.Timer(TRANSFER_TIMEOUT_SECONDS, interrupt)
        watchdog.daemon = True
        watchdog.start()
        connection.request("GET", endpoint, headers={"Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(_error_body(response))
        declared = response.getheader("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_CIPHERTEXT_BYTES):
            raise RuntimeError("Invalid or oversized ciphertext response")
        size = 0
        with destination.open("xb") as output:
            while chunk := response.read1(65536):
                size += len(chunk)
                if size > MAX_CIPHERTEXT_BYTES:
                    raise RuntimeError("Ciphertext exceeds the client's 100 MiB limit")
                if time.monotonic() - started >= TRANSFER_TIMEOUT_SECONDS:
                    raise RuntimeError("Download exceeded the time limit")
                output.write(chunk)
        if time.monotonic() - started >= TRANSFER_TIMEOUT_SECONDS:
            raise RuntimeError("Download exceeded the time limit")
        if declared is not None and size != int(declared):
            raise RuntimeError("Ciphertext response is truncated")
    except http.client.HTTPException as exc:
        raise RuntimeError(f"HTTP download error: {exc}") from exc
    finally:
        if watchdog is not None:
            watchdog.cancel()
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
        raise RuntimeError(f"HTTP delete error: {exc}") from exc
    finally:
        connection.close()



def list_transfers(server: str, after: str | None = None) -> dict[str, object]:
    """Fetch one bounded page; callers can follow next_cursor."""
    if after is not None and (len(after) != 32 or any(c not in
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for c in after)):
        raise ValueError("Invalid listing cursor")
    connection, prefix = _connection(server)
    endpoint = f"{prefix}/api/v1/transfers"
    if after is not None:
        endpoint += f"?after={after}"
    try:
        connection.request("GET", endpoint, headers={"Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(_error_body(response))
        body = response.read(65537)
        if len(body) > 65536:
            raise RuntimeError("Transfer listing exceeds the response limit")
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError("The server returned an invalid JSON listing") from exc
        if not isinstance(data, dict) or not isinstance(data.get("transfers"), list):
            raise RuntimeError("The server returned an invalid listing")
        return data
    except http.client.HTTPException as exc:
        raise RuntimeError(f"HTTP listing error: {exc}") from exc
    finally:
        connection.close()
