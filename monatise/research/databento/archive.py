"""Immutable native DBN archive. No network, trading or data transformations."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class NativeDBNArchive:
    """Operator-owned durable filesystem; chmod is not a substitute for WORM backups.

    Same-filesystem hard links publish without replacing an existing artifact.
    Staging names are deterministic so restart reconciles instead of redownloading.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        for name in ("staging", "objects", "quarantine"):
            (self.root / name).mkdir(parents=True, exist_ok=True, mode=0o700)

    @classmethod
    def open_existing(cls, root):
        """Read-only access to an existing archive; creates no directories."""
        instance = cls.__new__(cls)
        instance.root = Path(root).resolve()
        if not (instance.root / "objects").is_dir():
            raise ValueError("existing native archive required")
        return instance

    @staticmethod
    def _key(value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("archive key must be a SHA-256 digest")
        return value

    def staging(self, request_sha256):
        return self.root / "staging" / (self._key(request_sha256) + ".dbn.part")

    def object_path(self, digest):
        return self.root / "objects" / (self._key(digest) + ".dbn")

    def seal(self, request_sha256):
        source = self.staging(request_sha256)
        if source.is_symlink() or not source.is_file():
            raise ValueError("regular staged DBN file required")
        with source.open("rb") as stream:
            os.fsync(stream.fileno())
        digest = sha256_file(source)
        target = self.object_path(digest)
        os.chmod(source, 0o400)
        try:
            os.link(source, target)
        except FileExistsError:
            self.verify(digest)
        _fsync_directory(target.parent)
        source.unlink()
        _fsync_directory(source.parent)
        return digest

    def verify(self, digest):
        path = self.object_path(digest)
        if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
            raise ValueError("archive integrity verification failed")
        return path

    def quarantine(self, request_sha256):
        source = self.staging(request_sha256)
        if not source.exists():
            return None
        if source.is_symlink():
            raise ValueError("symlink staged artifact rejected")
        with source.open("rb") as stream:
            os.fsync(stream.fileno())
        digest = sha256_file(source)
        target = self.root / "quarantine" / (request_sha256 + "-" + digest + ".dbn.part")
        os.chmod(source, 0o400)
        try:
            os.link(source, target)
        except FileExistsError:
            if sha256_file(target) != digest:
                raise ValueError("quarantine hash conflict")
        _fsync_directory(target.parent)
        source.unlink()
        _fsync_directory(source.parent)
        return digest


def dbn_records(path, *, max_records=1_000_000, max_decoded_bytes=512 * 1024**2):
    """Stream original DBN versions; reject incomplete records and ZSTD frames.

    Yield metadata first, then records. SDK upgrading is disabled so the raw
    record hash describes the archived encoding, not a rewritten V3 record.
    A tiny compressed read bounds decompression working memory; total decoded
    bytes and records are independently limited. No dataframe materialization.
    """
    import databento_dbn as dbn
    import zstandard

    if not 1 <= max_records <= 1_000_000 or not 1 <= max_decoded_bytes <= 2 * 1024**3:
        raise ValueError("bounded decoder limits required")
    decoder = dbn.DBNDecoder(upgrade_policy=dbn.VersionUpgradePolicy.AS_IS)
    count, decoded_size, metadata_seen = 0, 0, False
    with Path(path).open("rb") as stream:
        prefix = stream.read(4)
        stream.seek(0)
        compressed = prefix == b"\x28\xb5\x2f\xfd"
        decompressor = zstandard.ZstdDecompressor().decompressobj() if compressed else None
        frame_complete = False
        while True:
            raw = stream.read(1024 if compressed else 65536)
            if not raw:
                break
            while raw:
                if compressed:
                    if frame_complete:
                        decompressor = zstandard.ZstdDecompressor().decompressobj()
                    chunk = decompressor.decompress(raw)
                    raw = decompressor.unused_data
                    frame_complete = decompressor.eof
                else:
                    chunk, raw = raw, b""
                decoded_size += len(chunk)
                if decoded_size > max_decoded_bytes:
                    raise ValueError("decoded byte capacity exceeded")
                for record in decoder.write_and_decode(chunk):
                    if isinstance(record, dbn.Metadata):
                        if metadata_seen:
                            raise ValueError("multiple DBN metadata headers rejected")
                        metadata_seen = True
                    else:
                        count += 1
                        if count > max_records:
                            raise ValueError("decoded record capacity exceeded")
                    yield record
        decoder.decode()  # advance past the last decoded record (pinned SDK behavior)
        if not metadata_seen or decoder.buffer() or (compressed and not frame_complete):
            raise ValueError("DBN archive truncated or incomplete")
