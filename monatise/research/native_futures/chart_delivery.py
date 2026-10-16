"""Checked local display projection; complete evidence stays in its snapshot."""
from copy import deepcopy
from pathlib import Path
from threading import Lock

from monatise.research.institutional.models import digest
from .cache import checked


def revision(path):
    s = Path(path).stat()
    return s.st_ino, s.st_mtime_ns, s.st_size


class CheckedChart:
    """Validate every new atomic file version, not the same file on every quote."""
    def __init__(self, path):
        self.path, self.lock, self.key, self.body, self.view = path, Lock(), None, None, None

    def read(self):
        with self.lock:
            key = revision(self.path)
            if key != self.key:
                body = checked(self.path)
                if body.get('version') != 'native-futures-chart-v1':
                    raise ValueError('native_chart_required')
                view = display_projection(body)
                # An atomic replacement during the read must be revalidated.
                if revision(self.path) != key:
                    raise ValueError('chart_replaced_during_read')
                self.key, self.body, self.view = key, body, view
            return self.body, self.view


def display_projection(body):
    """Keep every displayed value/hash; fetch /api/chart for complete provenance."""
    view = deepcopy(body)
    view['full_snapshot_sha256'] = digest(body)
    view['display_projection'] = 'PROVENANCE_REFERENCES; COMPLETE_LOCAL_SNAPSHOT_AT_/api/chart'
    for frames in view['charts'].values():
        for frame in frames.values():
            for bar in frame.get('bars', ()):
                sources = bar.pop('source_hashes', [])
                bar['source_hash_count'] = len(sources)
                bar['source_hashes_sha256'] = digest(sources)
    for info in view['analysis']['instruments'].values():
        for part in info.get('components', {}).values():
            if 'sparse_coverage_proofs' in part:
                proofs = part.pop('sparse_coverage_proofs')
                part['sparse_coverage_proof_references'] = list(proofs)
        info['full_snapshot_instrument_sha256'] = info.pop('reproducibility_sha256', None)
        info['reproducibility_sha256'] = digest(info)
    report = view['analysis']
    report['full_snapshot_report_sha256'] = report.pop('reproducibility_sha256', None)
    report['reproducibility_sha256'] = digest(report)
    return view
