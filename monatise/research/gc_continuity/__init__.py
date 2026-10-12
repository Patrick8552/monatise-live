"""Read-only GC continuity forensics and explicit, guarded recovery research."""

VERSION = "gc-continuity-forensics-v1"
PHASE3A = "0b3050d02afb563385f8a8f9286e2f56d87caeb8"
CLASS_NAMES = {
    "A": "VERIFIED_EXCHANGE_CLOSURE",
    "B": "VERIFIED_NO_TRADE_INTERVAL",
    "C": "VERIFIED_ACQUISITION_GAP",
    "D": "AGGREGATION_OR_ADMISSION_DEFECT",
    "E": "UNRESOLVED",
}
