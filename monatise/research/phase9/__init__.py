"""Opt-in, read-only Phase 9 research. Nothing is registered at application startup."""
from monatise.research.databento.live_models import SAFETY as _SAFETY

VERSION = 'monatise-phase9-v1'
SAFETY = dict(_SAFETY, approval_created=False, orders_placed=0, production_GIL_compatible=False)
