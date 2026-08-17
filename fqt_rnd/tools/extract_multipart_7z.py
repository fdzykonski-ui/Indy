#!/usr/bin/env python3
"""Safely inspect or extract a split 7z archive with system libarchive.

The upload layer may prefix filenames, so volume order is derived exclusively
from the final numeric suffix (``.001``, ``.002``, ...).  Original volumes are
read-only.  A temporary concatenated archive is removed after the operation.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath


ARCHIVE_OK = 0
ARCHIVE_EOF = 1
VOLUME_RE = re.compile(r"\.(\d{3})$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ordered_volumes(paths: list[Path]) -> list[Path]:
    indexed: dict[int, Path] = {}
    for path in paths:
        match = VOLUME_RE.search(path.name)
        if not match:
            raise ValueError(f"Not a numbered 7z volume: {path}")
        index = int(match.group(1))
        if index in indexed:
            raise ValueError(f"Duplicate volume index {index:03d}: {indexed[index]} and {path}")
        if not path.is_file():
            raise FileNotFoundError(path)
        indexed[index] = path
    expected = list(range(1, max(indexed, default=0) + 1))
    if sorted(indexed) != expected:
        raise ValueError(f"Volume sequence is incomplete: got {sorted(indexed)}, expected {expected}")
    return [indexed[index] for index in expected]


def safe_relative_path(raw_name: str) -> Path:
    posix = PurePosixPath(raw_name)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError(f"Unsafe archive path: {raw_name!r}")
    clean_parts = tuple(part for part in posix.parts if part not in ("", "."))
    if not clean_parts:
        raise ValueError(f"Empty archive path: {raw_name!r}")
    return Path(*clean_parts)


class LibArchive:
    def __init__(self) -> None:
        library_name = ctypes.util.find_library("archive")
        if not library_name:
            raise RuntimeError("system libarchive was not found")
        self.lib = ctypes.CDLL(library_name)
        self.lib.archive_read_new.restype = ctypes.c_void_p
        self.lib.archive_read_support_filter_all.argtypes = [ctypes.c_void_p]
        self.lib.archive_read_support_format_all.argtypes = [ctypes.c_void_p]
        self.lib.archive_read_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        self.lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.lib.archive_read_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        self.lib.archive_read_data.restype = ctypes.c_ssize_t
        self.lib.archive_read_data_skip.argtypes = [ctypes.c_void_p]
        self.lib.archive_read_free.argtypes = [ctypes.c_void_p]
        self.lib.archive_error_string.argtypes = [ctypes.c_void_p]
        self.lib.archive_error_string.restype = ctypes.c_char_p
        self.lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
        self.lib.archive_entry_pathname.restype = ctypes.c_char_p
        self.lib.archive_entry_size.argtypes = [ctypes.c_void_p]
        self.lib.archive_entry_size.restype = ctypes.c_int64
        self.lib.archive_entry_mode.argtypes = [ctypes.c_void_p]
        self.lib.archive_entry_mode.restype = ctypes.c_uint
        self.lib.archive_entry_symlink.argtypes = [ctypes.c_void_p]
        self.lib.archive_entry_symlink.restype = ctypes.c_char_p
        self.lib.archive_entry_hardlink.argtypes = [ctypes.c_void_p]
        self.lib.archive_entry_hardlink.restype = ctypes.c_char_p

    def error(self, archive: int) -> str:
        value = self.lib.archive_error_string(archive)
        return value.decode("utf-8", "replace") if value else "unknown libarchive error"


def combine_volumes(volumes: list[Path], target: Path) -> list[dict[str, object]]:
    metadata = []
    with target.open("wb") as output:
        for index, volume in enumerate(volumes, 1):
            metadata.append({
                "index": index,
                "source": str(volume.resolve()),
                "bytes": volume.stat().st_size,
                "sha256": sha256_file(volume),
            })
            with volume.open("rb") as source:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
    return metadata


def inspect_or_extract(archive_path: Path, destination: Path | None) -> dict[str, object]:
    api = LibArchive()
    archive = api.lib.archive_read_new()
    if not archive:
        raise RuntimeError("archive_read_new failed")
    extracted_files = 0
    directories = 0
    symlinks = 0
    skipped_special = 0
    total_bytes = 0
    total_entries = 0
    type_counts = {"regular": 0, "directory": 0, "symlink": 0, "other": 0}
    sample: list[dict[str, object]] = []
    interesting: list[dict[str, object]] = []
    try:
        for setup in (api.lib.archive_read_support_filter_all, api.lib.archive_read_support_format_all):
            if setup(archive) < ARCHIVE_OK:
                raise RuntimeError(api.error(archive))
        result = api.lib.archive_read_open_filename(archive, os.fsencode(archive_path), 1024 * 1024)
        if result < ARCHIVE_OK:
            raise RuntimeError(api.error(archive))
        if destination is not None:
            destination.mkdir(parents=True, exist_ok=True)
            destination = destination.resolve()
        entry = ctypes.c_void_p()
        buffer = ctypes.create_string_buffer(1024 * 1024)
        while True:
            result = api.lib.archive_read_next_header(archive, ctypes.byref(entry))
            if result == ARCHIVE_EOF:
                break
            if result < ARCHIVE_OK:
                raise RuntimeError(api.error(archive))
            raw = api.lib.archive_entry_pathname(entry)
            if raw is None:
                raise RuntimeError("archive entry has no pathname")
            name = raw.decode("utf-8", "surrogateescape")
            relative = safe_relative_path(name)
            size = max(0, int(api.lib.archive_entry_size(entry)))
            mode = int(api.lib.archive_entry_mode(entry))
            kind = stat.S_IFMT(mode)
            total_entries += 1
            if kind == stat.S_IFDIR:
                type_counts["directory"] += 1
            elif kind == stat.S_IFREG or kind == 0:
                type_counts["regular"] += 1
            elif kind == stat.S_IFLNK:
                type_counts["symlink"] += 1
            else:
                type_counts["other"] += 1
            if len(sample) < 200:
                sample.append({"path": name, "bytes": size, "mode": oct(mode)})
            lowered = name.lower()
            if len(interesting) < 1000 and any(
                token in lowered
                for token in ("user_data/", "strateg", "config", "backtest", "hyperopt", "/logs/")
            ):
                interesting.append({"path": name, "bytes": size, "mode": oct(mode)})

            if destination is None:
                api.lib.archive_read_data_skip(archive)
                total_bytes += size
                continue

            output_path = (destination / relative).resolve(strict=False)
            if destination not in output_path.parents and output_path != destination:
                raise ValueError(f"Archive path escapes destination: {name!r}")

            if kind == stat.S_IFDIR:
                output_path.mkdir(parents=True, exist_ok=True)
                directories += 1
                continue

            if kind == stat.S_IFREG or kind == 0:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                written = 0
                with output_path.open("wb") as output:
                    while True:
                        count = int(api.lib.archive_read_data(archive, buffer, len(buffer)))
                        if count == 0:
                            break
                        if count < 0:
                            raise RuntimeError(api.error(archive))
                        payload = buffer.raw[:count]
                        output.write(payload)
                        digest.update(payload)
                        written += count
                if written != size:
                    raise RuntimeError(f"Size mismatch for {name}: metadata={size}, extracted={written}")
                os.chmod(output_path, stat.S_IMODE(mode) or 0o644)
                extracted_files += 1
                total_bytes += written
                continue

            if kind == stat.S_IFLNK:
                target_raw = api.lib.archive_entry_symlink(entry)
                target = target_raw.decode("utf-8", "surrogateescape") if target_raw else ""
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # Preserve only relative links that remain within the extraction root.
                target_path = (output_path.parent / target).resolve(strict=False)
                if not target or Path(target).is_absolute() or (
                    destination not in target_path.parents and target_path != destination
                ):
                    skipped_special += 1
                else:
                    output_path.symlink_to(target)
                    symlinks += 1
                api.lib.archive_read_data_skip(archive)
                continue

            # Hardlinks and device-like entries are skipped rather than materialized.
            skipped_special += 1
            api.lib.archive_read_data_skip(archive)
    finally:
        api.lib.archive_read_free(archive)
    return {
        "regular_files": extracted_files,
        "directories": directories,
        "symlinks": symlinks,
        "skipped_special": skipped_special,
        "uncompressed_regular_bytes": total_bytes,
        "archive_entries": total_entries,
        "archive_type_counts": type_counts,
        "entry_sample": sample,
        "interesting_entries": interesting,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("parts", nargs="+", type=Path)
    parser.add_argument("--destination", type=Path, help="Extract here; omit for list/inspect mode")
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    volumes = ordered_volumes(args.parts)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fqt_7z_") as temporary:
        combined = Path(temporary) / "combined.7z"
        volume_metadata = combine_volumes(volumes, combined)
        archive_metadata = inspect_or_extract(combined, args.destination)
        manifest = {
            "format": "split-7z",
            "combined_bytes": combined.stat().st_size,
            "combined_sha256": sha256_file(combined),
            "volumes": volume_metadata,
            "destination": str(args.destination.resolve()) if args.destination else None,
            **archive_metadata,
        }
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        key: value
        for key, value in manifest.items()
        if key not in {"entry_sample", "interesting_entries"}
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
