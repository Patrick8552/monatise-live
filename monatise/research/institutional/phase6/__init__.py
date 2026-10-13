"""Phase 6 offline research. No registration in the production application."""
from .. import SAFETY

BASELINE = '51988f0ced35ee6bbe378174e80b57f2c9943a47'
VERSION = 'monatise-phase6-research-v1'
POLICY = dict(scope='ISOLATED_GC_OPTIONS_RESEARCH_ONLY', mandatory_providers=(),
              production_routing_changed=False, canonical_index_requirements_preserved=True)
