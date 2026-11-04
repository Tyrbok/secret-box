"""Interfaz de línea de comandos de secret-box."""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import tempfile
from pathlib import Path

from . import __version__
from .age import decrypt_bundle, encrypt_bundle, generate_identity
from .api import delete as delete_transfer
from .api import download, upload
from .bundle import extract_bundle
from .config import configure, connection_settings, identity_dir, server_setting


TRANSFER_ID = re.compile(r"^[A-Za-z0-9_-]{32}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb", description="Envía contenido cifrado entre máquinas")
    parser.add_argument("--version", action="version", version=f"sb {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("configure", help="Configura URL del servidor y token")

    send_parser = subparsers.add_parser("send", help="Cifra y envía un archivo, carpeta o texto")
    send_parser.add_argument("source", nargs="?", type=Path, help="Archivo o carpeta que enviar")
    send_parser.add_argument("--text", action="store_true", help="Lee texto desde la entrada estándar")
    send_parser.add_argument("--recipient", help="Clave pública age del equipo destinatario")
    send_parser.add_argument("--server", help="Sobrescribe la URL configurada")

    receive_parser = subparsers.add_parser("receive", help="Descarga, descifra y restaura un envío")
    receive_parser.add_argument("transfer_id", help="Identificador de 32 caracteres")
    receive_parser.add_argument("--output", type=Path, help="Archivo/carpeta de destino; texto va a stdout si se omite")
    receive_parser.add_argument("--identity", action="append", type=Path, default=[], help="Identidad age privada (se puede repetir)")
    receive_parser.add_argument("--server", help="Sobrescribe la URL configurada")

    delete_parser = subparsers.add_parser("delete", help="Elimina un envío del servidor")
    delete_parser.add_argument("transfer_id", help="Identificador de 32 caracteres")
    delete_parser.add_argument("--server", help="Sobrescribe la URL configurada")

    key_parser = subparsers.add_parser("keygen", help="Crea una identidad age para este equipo")
    key_parser.add_argument("--name", required=True, help="Nombre local de la identidad")
    return parser


def _check_id(value: str) -> str:
    if not TRANSFER_ID.fullmatch(value):
        raise ValueError("El identificador debe tener 32 caracteres Base64 URL-safe")
    return value


def _send(args: argparse.Namespace) -> None:
    if bool(args.text) == bool(args.source):
        raise ValueError("Indica un archivo/carpeta o usa --text, pero no ambos")
    text: bytes | None = None
    source: Path | None = args.source
    if args.text:
        if sys.stdin.isatty():
            print("Pega el texto y termina con Ctrl-D:", file=sys.stderr)
        text = sys.stdin.buffer.read()
        if not text:
            raise ValueError("No se recibió texto")
    server, token = connection_settings(args.server)
    with tempfile.TemporaryDirectory(prefix="secretbox-") as temporary:
        encrypted = Path(temporary) / "transfer.age"
        encrypt_bundle(encrypted, source=source, text=text, recipient=args.recipient)
        result = upload(server, token, encrypted)
    transfer_id = result.get("id")
    expires = result.get("expires_at")
    if not isinstance(transfer_id, str) or not TRANSFER_ID.fullmatch(transfer_id):
        raise RuntimeError("El servidor devolvió un identificador inválido")
    print(f"ID: {transfer_id}")
    print(f"Caduca: {expires}")
    print("Comparte el ID. Si usaste passphrase, compártela por otro canal.")


def _receive(args: argparse.Namespace) -> None:
    transfer_id = _check_id(args.transfer_id)
    server = server_setting(args.server)
    with tempfile.TemporaryDirectory(prefix="secretbox-") as temporary:
        encrypted = Path(temporary) / "transfer.age"
        bundle = Path(temporary) / "transfer.tar.gz"
        download(server, transfer_id, encrypted)
        decrypt_bundle(encrypted, bundle, args.identity)
        result = extract_bundle(bundle, args.output)
    if result is not None:
        print(f"Guardado en: {result}")


def _delete(args: argparse.Namespace) -> None:
    transfer_id = _check_id(args.transfer_id)
    server, token = connection_settings(args.server)
    delete_transfer(server, token, transfer_id)
    print(f"Transferencia {transfer_id} eliminada")


def _keygen(args: argparse.Namespace) -> None:
    path, recipient = generate_identity(args.name, identity_dir())
    print(f"Clave privada: {path}")
    print(f"Clave pública: {recipient}")
    print("Guarda la clave privada solo en el equipo que descifrará.")


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "configure":
            configure()
        elif args.command == "send":
            _send(args)
        elif args.command == "receive":
            _receive(args)
        elif args.command == "delete":
            _delete(args)
        elif args.command == "keygen":
            _keygen(args)
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as exc:
        print(f"sb: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

