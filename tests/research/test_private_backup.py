"""Offline recovery-integrity tests; all evidence and keys are generated fixtures."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import secrets
import tarfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import pytest

spec = importlib.util.spec_from_file_location(
    "backup_verifier", Path(__file__).parents[2] / "scripts/verify_private_research_backup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path, *, wrong_hash=False, duplicate=False):
    content = b"synthetic research evidence only"
    manifest = json.dumps({"files": [{"bytes": len(content), "sha256":
        "0" * 64 if wrong_hash else hashlib.sha256(content).hexdigest()}]}).encode()
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for name, data in [("manifest.json", manifest), ("evidence/00000000", content)] + (
                [("evidence/00000000", content)] if duplicate else []):
            info = tarfile.TarInfo(name); info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    key = secrets.token_bytes(32)
    header = module.MAGIC + secrets.token_bytes(module.NONCE_BYTES)
    cipher = Cipher(algorithms.AES(key), modes.GCM(header[-module.NONCE_BYTES:])).encryptor()
    cipher.authenticate_additional_data(header)
    encrypted = header + cipher.update(payload.getvalue()) + cipher.finalize() + cipher.tag
    backup, keyfile, inventory = (tmp_path / n for n in ["evidence.enc", "key", "manifest.json"])
    backup.write_bytes(encrypted); keyfile.write_bytes(key); inventory.write_bytes(manifest)
    return backup, keyfile, inventory


def test_all_evidence_authenticated_and_verified(tmp_path):
    paths = fixture(tmp_path)
    result = module.verify(*paths)
    assert result["authenticated"] and result["files_verified"] == 1
    assert result["encrypted_backup_sha256"] == hashlib.sha256(paths[0].read_bytes()).hexdigest()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["evidence.enc", "key", "manifest.json"]


@pytest.mark.parametrize("damage", ["key", "ciphertext", "tag"])
def test_authentication_failure_precedes_archive_parsing(tmp_path, monkeypatch, damage):
    backup, keyfile, inventory = fixture(tmp_path)
    path = keyfile if damage == "key" else backup
    data = bytearray(path.read_bytes())
    index = 0 if damage == "key" else (-1 if damage == "tag" else len(module.MAGIC) + 12 + 1)
    data[index] ^= 1; path.write_bytes(data)
    def forbidden(*args, **kwargs):
        raise AssertionError("unauthenticated archive parsed")
    monkeypatch.setattr(module.tarfile, "open", forbidden)
    with pytest.raises(InvalidTag):
        module.verify(backup, keyfile, inventory)


@pytest.mark.parametrize("fault", ["hash", "manifest", "duplicate", "truncated"])
def test_evidence_integrity_rejections(tmp_path, fault):
    backup, keyfile, inventory = fixture(tmp_path, wrong_hash=fault == "hash", duplicate=fault == "duplicate")
    if fault == "manifest":
        inventory.write_bytes(inventory.read_bytes() + b"\n")
    if fault == "truncated":
        backup.write_bytes(b"short")
    with pytest.raises(ValueError):
        module.verify(backup, keyfile, inventory)
