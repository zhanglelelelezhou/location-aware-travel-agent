from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_portfolio_demo_runs_offline_end_to_end() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo_portfolio.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "复合请求：规划并调用两个工具" in result.stdout
    assert "人工确认：批准前零执行，令牌不可重放" in result.stdout
    assert '"external_request_sent": false' in result.stdout
    assert '"replay": "invalid_or_expired"' in result.stdout
    assert "Demo completed" in result.stdout
