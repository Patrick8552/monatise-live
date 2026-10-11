"""Offline native GC diagnostics, deliberately absent from production routing."""

POLICY = "gold-fib-h1-structural-leg-v1"
H1_RESEARCH = "f1de9d46cb5f3458726b81cfbc9f1d0dfba73f35"
BASELINE = "890b8f7deba379931a3ce7df5b6e6fb5760f2d73"
ISOLATION = {name: False for name in (
    "publication_enabled", "approval_eligible", "pending_order_eligible",
    "execution_enabled", "production_integrated", "gil_enabled", "pit_verified")}
