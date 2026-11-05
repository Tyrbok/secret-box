"""Bundle creation and safe extraction before age encryption."""

from __future__ import annotations

import gzip
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO


MANIFEST = "secretbox-manifest.json"
MAX_MANIFEST_BYTES = 16 * 1024
MAX_ARCHIVE_ENTRIES = 100_000
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024


def _safe_name(name: str) -> str:
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or "\x00" in name
    ):
        raise ValueError(f"Invalid file name: {name!r}")
    return name


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    if not (info.isfile() or info.isdir()):
        raise ValueError(f"Symbolic links and special files are not supported: {info.name}")
    return info


def write_bundle(
    output: BinaryIO,
    *,
    source: Path | None = None,
    text: bytes | None = None,
) -> None:
    if (source is None) == (text is None):
        raise ValueError("Specify exactly one file, directory, or text input")

    if text is not None:
        name = "text.txt"
        kind = "text"
    else:
        assert source is not None
        source = source.expanduser()
        if not source.exists():
            raise ValueError(f"No existe: {source}")
        if source.is_symlink():
            raise ValueError("Symbolic links cannot be used as a source")
        if not (source.is_file() or source.is_dir()):
            raise ValueError("Source must be a regular file or directory")
        name = _safe_name(source.name)
        kind = "directory" if source.is_dir() else "file"

    manifest = json.dumps(
        {"version": 1, "kind": kind, "name": name},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    with gzip.GzipFile(
        fileobj=output,
        mode="wb",
        compresslevel=6,
        filename="",
    ) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(manifest)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(manifest))
            if text is not None:
                info = tarfile.TarInfo("payload/text.txt")
                info.size = len(text)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(text))
            else:
                assert source is not None
                archive.add(
                    str(source),
                    arcname=f"payload/{name}",
                    recursive=source.is_dir(),
                    filter=_tar_filter,
                )


def _read_manifest(archive: tarfile.TarFile) -> tuple[dict[str, object], tarfile.TarInfo]:
    first = archive.next()
    if first is None or first.name != MANIFEST or not first.isfile() or first.size > MAX_MANIFEST_BYTES:
        raise ValueError("Bundle does not contain a valid manifest")
    stream = archive.extractfile(first)
    if stream is None:
        raise ValueError("Could not read the bundle manifest")
    try:
        data = json.loads(stream.read(MAX_MANIFEST_BYTES + 1).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported bundle version")
    if data.get("kind") not in {"file", "directory", "text"}:
        raise ValueError("Invalid content type")
    if not isinstance(data.get("name"), str):
        raise ValueError("Invalid content name")
    data["name"] = _safe_name(data["name"])
    return data, first


def _extract_to_stage(archive: tarfile.TarFile, stage: Path, manifest: dict[str, object], manifest_offset: int) -> Path:
    name = str(manifest["name"])
    kind = str(manifest["kind"])
    total_size = 0
    seen: set[str] = set()
    payload_root = stage / "payload"
    payload_root.mkdir(mode=0o700)

    entries = 1
    for member in archive:
        if member.offset == manifest_offset:
            continue
        entries += 1
        if entries > MAX_ARCHIVE_ENTRIES:
            raise ValueError("Bundle contains too many entries")
        if member.name in seen:
            raise ValueError("Bundle contains duplicate paths")
        seen.add(member.name)
        raw_name = member.name
        path = PurePosixPath(raw_name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in raw_name
            or "\x00" in raw_name
            or not path.parts
            or path.parts[0] != "payload"
        ):
            raise ValueError("Bundle contains an unsafe path")
        if not (member.isfile() or member.isdir()):
            raise ValueError("Bundle contains links or special files")
        if kind == "text" and raw_name != "payload/text.txt":
            raise ValueError("Text bundle contains unexpected paths")
        if kind == "text" and not member.isfile():
            raise ValueError("Text content must be a regular file")
        if kind == "file" and raw_name != f"payload/{name}":
            raise ValueError("File bundle contains unexpected paths")
        if kind == "directory" and path.parts[1:2] != (name,):
            raise ValueError("Directory bundle contains unexpected paths")

        target = stage.joinpath(*path.parts)
        if not target.resolve().is_relative_to(stage.resolve()):
            raise ValueError("Extraction path escapes the destination")
        if member.isdir():
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            continue
        total_size += member.size
        if member.size < 0 or total_size > MAX_EXTRACTED_BYTES:
            raise ValueError("Content exceeds the local extraction limit")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise ValueError(f"Could not read {member.name}")
        remaining = member.size
        with target.open("xb") as output:
            os.chmod(target, 0o600)
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError(f"File {member.name} is truncated")
                output.write(chunk)
                remaining -= len(chunk)

    if kind == "text":
        expected = "payload/text.txt"
        if expected not in seen:
            raise ValueError("Text content is missing")
        return payload_root / "text.txt"
    if kind == "file":
        expected = f"payload/{name}"
        if expected not in seen or not (payload_root / name).is_file():
            raise ValueError("Bundle file is missing")
        return payload_root / name
    directory = payload_root / name
    if not directory.is_dir():
        raise ValueError("Bundle directory is missing")
    return directory


def extract_bundle(bundle_path: Path, output_path: Path | None = None) -> Path | None:
    with tarfile.open(bundle_path, mode="r:gz") as archive:
        manifest, manifest_entry = _read_manifest(archive)
        kind = str(manifest["kind"])
        name = str(manifest["name"])
        with tempfile.TemporaryDirectory(prefix="secretbox-unpack-") as temporary:
            stage = Path(temporary)
            extracted = _extract_to_stage(archive, stage, manifest, manifest_entry.offset)
            if kind == "text" and output_path is None:
                text = extracted.read_bytes().decode("utf-8")
                sys.stdout.write(text)
                return None
            if kind == "text":
                target = output_path.expanduser() if output_path else Path(name)
            else:
                target = output_path.expanduser() if output_path else Path(name)
            target = target.absolute()
            if target.exists() or target.is_symlink():
                raise FileExistsError(f"El destino ya existe: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extracted), str(target))
            return target

