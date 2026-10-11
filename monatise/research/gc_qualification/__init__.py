"""Offline native GC analytical qualification; never a production route."""

VERSION = "gc-qualification-v1"
BASELINE = "3340bfc5bd136a3b9e51e6185a9f54222c4b4f37"
FROZEN = "f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35"
AVAILABILITY = "RETROSPECTIVE_ASSUMED_AVAILABILITY"
SAFETY = dict(execution_enabled=False, publication_enabled=False,
              approval_enabled=False, live_integration_enabled=False, gil_enabled=False)

