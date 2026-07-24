from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "app.js"
INDEX_HTML = ROOT / "app" / "index.html"


def test_dashboard_javascript_has_valid_syntax() -> None:
    node = shutil.which("node")
    if node is None:
        return
    result = subprocess.run([node, "--check", str(APP_JS)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_dashboard_does_not_restore_removed_london_runtime_gate() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "app").glob("*.js"))
    assert "londonSession(" not in source
    assert "commodityLondonGuard(" not in source
    assert "londonCommodityInput" not in source
    assert "London/New York" not in source


def test_dashboard_does_not_restore_payment_or_execution_controls() -> None:
    source = (APP_JS.read_text(encoding="utf-8") + INDEX_HTML.read_text(encoding="utf-8")).lower()
    for removed_surface in ("stripe", "billingcheckout", "support with usdc", "usdc payment required"):
        assert removed_surface not in source
