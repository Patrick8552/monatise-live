from dataclasses import dataclass
import pytest
from monatise.research.databento.live_journal import NativeJournal, verify
from monatise.research.institutional.phase7.batched_journal import BatchedNativeJournal


@dataclass
class Scope:
    schemas: tuple = ('definition',)
    maximum_records: int = 5
    maximum_bytes: int = 1000
    sha256: str = 'a' * 64


def test_batch_preserves_original_phase6_framing_and_durable_verification(tmp_path):
    scope = Scope()
    plain = NativeJournal(tmp_path/'plain', schema='definition', scope=scope,
                          evidence_kind='ENGINEERING_SYNTHETIC')
    batched = BatchedNativeJournal(tmp_path/'batch', schema='definition', scope=scope,
                                   evidence_kind='ENGINEERING_SYNTHETIC')
    records = [(10,b'original1'),(20,b'original2'),(20,b'original3')]
    for at, row in records:
        plain.append(row,capture_ns=at)
    batched.append_batch(records[:2])
    batched.append_batch(records[2:])
    for journal in (plain,batched):
        journal.close(quality={'quarantined':False},checkpoint={})
    left, right = verify(tmp_path/'plain'), verify(tmp_path/'batch')
    assert left[1] == right[1] == tuple(records)
    assert left[0]['raw_sha256'] == right[0]['raw_sha256']


@pytest.mark.parametrize('records', [[],[(20,b'x'),(10,b'y')],[(10,b'')],[(0,b'x')],[(10,b'x')]*6])
def test_rejected_batch_does_not_mutate_bytes_or_cursor(tmp_path, records):
    journal = BatchedNativeJournal(tmp_path/'rejected',schema='definition',scope=Scope())
    original = journal.path.read_bytes()
    with pytest.raises(ValueError):
        journal.append_batch(records)
    assert journal.count == 0 and journal.last_capture == 0
    assert journal.path.read_bytes() == original
    journal.close(quality={'quarantined':True},checkpoint={})
    with pytest.raises(ValueError,match='quarantined'):
        verify(tmp_path/'rejected')


def test_fsync_failure_never_advances_cursor_or_admits_partial_archive(tmp_path,monkeypatch):
    journal = BatchedNativeJournal(tmp_path/'failed',schema='definition',scope=Scope())
    def failure(_): raise OSError('simulated storage failure')
    monkeypatch.setattr('os.fsync',failure)
    with pytest.raises(OSError): journal.append_batch([(10,b'original')])
    assert journal.count == 0 and journal.last_capture == 0
    journal.file.close()
    assert not (tmp_path/'failed'/'manifest.json').exists()
    with pytest.raises(FileNotFoundError): verify(tmp_path/'failed')
