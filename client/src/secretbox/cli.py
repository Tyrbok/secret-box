"""Command-line interface for secret-box."""

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
from .api import download, list_transfers, upload
from .bundle import extract_bundle
from .config import configure, connection_settings, identity_dir, server_setting


TRANSFER_ID = re.compile(r"^[A-Za-z0-9_-]{32}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb", description="Send encrypted content between devices")
    parser.add_argument("--version", action="version", version=f"sb {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("configure", help="Configure the server URL and upload token")

    send_parser = subparsers.add_parser("send", help="Encrypt and send a file, directory, or text")
    send_parser.add_argument("source", nargs="?", type=Path, help="File or directory to send")
    send_parser.add_argument("--text", action="store_true", help="Read text from standard input")
    send_parser.add_argument("--recipient", help="Recipient device's age public key")
    send_parser.add_argument("--server", help="Override the configured server URL")

    send_parser.add_argument("--listable", action="store_true", help="Include this encrypted transfer in the listing")

    list_parser = subparsers.add_parser("list", help="List discoverable, unexpired transfers")
    list_parser.add_argument("--server", help="Override the configured server URL")
    list_parser.add_argument("--after", help="Fetch the page after this transfer ID")

    receive_parser = subparsers.add_parser("receive", help="Download, decrypt, and restore a transfer")
    receive_parser.add_argument("transfer_id", help="32-character transfer ID")
    receive_parser.add_argument("--output", type=Path, help="Destination path; text goes to stdout if omitted")
    receive_parser.add_argument("--identity", action="append", type=Path, default=[], help="Private age identity (may be repeated)")
    receive_parser.add_argument("--server", help="Override the configured server URL")

    delete_parser = subparsers.add_parser("delete", help="Delete a transfer from the server")
    delete_parser.add_argument("transfer_id", help="32-character transfer ID")
    delete_parser.add_argument("--server", help="Override the configured server URL")

    key_parser = subparsers.add_parser("keygen", help="Create an age identity for this device")
    key_parser.add_argument("--name", required=True, help="Local identity name")
    return parser


def _check_id(value: str) -> str:
    if not TRANSFER_ID.fullmatch(value):
        raise ValueError("Transfer ID must contain 32 URL-safe Base64 characters")
    return value


def _send(args: argparse.Namespace) -> None:
    if bool(args.text) == bool(args.source):
        raise ValueError("Specify a file or directory, or use --text, but not both")
    text: bytes | None = None
    source: Path | None = args.source
    if args.text:
        if sys.stdin.isatty():
            print("Paste the text and press Ctrl-D to finish:", file=sys.stderr)
        text = sys.stdin.buffer.read()
        if not text:
            raise ValueError("No text was received")
    server, token = connection_settings(args.server)
    with tempfile.TemporaryDirectory(prefix="secretbox-") as temporary:
        encrypted = Path(temporary) / "transfer.age"
        encrypt_bundle(encrypted, source=source, text=text, recipient=args.recipient)
        result = upload(server, token, encrypted, listable=args.listable)
    transfer_id = result.get("id")
    expires = result.get("expires_at")
    if not isinstance(transfer_id, str) or not TRANSFER_ID.fullmatch(transfer_id):
        raise RuntimeError("The server returned an invalid transfer ID")
    if args.listable and result.get("listable") is not True:
        raise RuntimeError(
            f"Transfer {transfer_id} was uploaded, but the server did not confirm public listing; "
            "update the server to support --listable"
        )
    print(f"ID: {transfer_id}")
    print(f"Expires: {expires}")
    print(f"Listable: {'yes' if args.listable else 'no'}")
    print("Share the ID. If you used a passphrase, share it through another channel.")


def _list(args: argparse.Namespace) -> None:
    after = _check_id(args.after) if args.after else None
    server = server_setting(args.server)
    result = list_transfers(server, after)
    rows = result["transfers"]
    if not isinstance(rows, list) or len(rows) > 100:
        raise RuntimeError("The server returned an invalid listing")
    lines = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("The server returned an invalid listing")
        transfer_id = row.get("id")
        size = row.get("size")
        dates = [row.get("created_at"), row.get("expires_at")]
        if (not isinstance(transfer_id, str) or not TRANSFER_ID.fullmatch(transfer_id)
                or type(size) is not int or size < 1
                or any(not isinstance(date, str) or not date.isascii()
                       or any(c not in "0123456789-T:+.Z" for c in date) for date in dates)):
            raise RuntimeError("The server returned an invalid listing")
        lines.append(f"{transfer_id}\t{size}\t{dates[0]}\t{dates[1]}")
    cursor = result.get("next_cursor")
    if cursor is not None:
        if not isinstance(cursor, str):
            raise RuntimeError("The server returned an invalid listing cursor")
        _check_id(cursor)
    if lines:
        print("ID\tBYTES\tCREATED\tEXPIRES")
        print("\n".join(lines))
    else:
        print("No listable transfers.")
    if cursor:
        print(f"Next page: sb list --after {cursor}")


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
        print(f"Saved to: {result}")


def _delete(args: argparse.Namespace) -> None:
    transfer_id = _check_id(args.transfer_id)
    server, token = connection_settings(args.server)
    delete_transfer(server, token, transfer_id)
    print(f"Transfer {transfer_id} deleted")


def _keygen(args: argparse.Namespace) -> None:
    path, recipient = generate_identity(args.name, identity_dir())
    print(f"Private key: {path}")
    print(f"Public key: {recipient}")
    print("Keep the private key only on the device that will decrypt transfers.")


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "configure":
            configure()
        elif args.command == "send":
            _send(args)
        elif args.command == "list":
            _list(args)
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

