"""Authenticate a local research backup and verify every archived evidence hash.

This offline utility never extracts files or contacts providers. The recovery key
and detailed manifest remain private. See docs/continuity/private-evidence-backup.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"MONATISE-RESEARCH-BACKUP\x01"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_BYTES = 1024 * 1024


def verify(backup: Path, key_path: Path, manifest_path: Path) -> dict:
    """Authenticate before parsing; compare against an independently saved manifest."""
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError("recovery key must contain exactly 32 binary bytes")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    rows = manifest["files"]
    if not rows or any(row["bytes"] < 0 for row in rows):
        raise ValueError("invalid evidence inventory")
    with backup.open("rb") as source, tempfile.TemporaryFile() as plaintext:
        size = backup.stat().st_size
        header_size = len(MAGIC) + NONCE_BYTES
        if size <= header_size + TAG_BYTES:
            raise ValueError("truncated backup")
        header = source.read(header_size)
        if header[:len(MAGIC)] != MAGIC:
            raise ValueError("unsupported backup format")
        source.seek(-TAG_BYTES, 2)
        tag = source.read(TAG_BYTES)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(header[-NONCE_BYTES:], tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        source.seek(header_size)
        remaining = size - header_size - TAG_BYTES
        while remaining:
            chunk = source.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                raise ValueError("truncated ciphertext")
            plaintext.write(decryptor.update(chunk))
            remaining -= len(chunk)
        plaintext.write(decryptor.finalize())  # InvalidTag stops before any tar parsing.
        plaintext.seek(0)
        expected = {f"evidence/{i:08d}": row for i, row in enumerate(rows)}
        seen = set()
        with tarfile.open(fileobj=plaintext, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile() or member.name in seen:
                    raise ValueError("invalid or duplicate archive member")
                seen.add(member.name)
                stream = archive.extractfile(member)
                if member.name == "manifest.json":
                    if member.size != len(manifest_bytes) or stream.read() != manifest_bytes:
                        raise ValueError("private manifest mismatch")
                    continue
                row = expected.get(member.name)
                if row is None or member.size != row["bytes"]:
                    raise ValueError("unexpected evidence member or size")
                digest = hashlib.sha256()
                while chunk := stream.read(CHUNK_BYTES):
                    digest.update(chunk)
                if digest.hexdigest() != row["sha256"]:
                    raise ValueError("evidence hash mismatch")
        if seen != set(expected) | {"manifest.json"}:
            raise ValueError("incomplete evidence archive")
    digest = hashlib.sha256()
    with backup.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return {"authenticated": True, "files_verified": len(rows),
            "evidence_bytes": sum(row["bytes"] for row in rows),
            "encrypted_backup_sha256": digest.hexdigest(),
            "private_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.backup, args.key_file, args.manifest), sort_keys=True))
