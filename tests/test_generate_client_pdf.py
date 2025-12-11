from pathlib import Path
from generate_client_pdf import build_report
from datetime import date, timedelta


def test_build_report_creates_pdf(tmp_path: Path) -> None:
    out = tmp_path / "test_report.pdf"
    today = date.today()
    start = today - timedelta(days=30)
    # run generator (demo allocations)
    result = build_report("CUST-UNITTEST", start, today, output=str(out), demo=True)
    assert result == str(out)
    assert out.exists()
    assert out.stat().st_size > 0
