import json

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.statistical import IQRDetector
from anomaly_lab.evaluation.backtest import backtest_detector
from anomaly_lab.evaluation.report import build_report, diff_reports


def test_build_report_writes_json_md_and_figures(tmp_path):
    series = [
        generate_series(c, n=300, seed=70 + i)
        for i, c in enumerate(["stationary", "periodic", "trending"])
    ]
    rows = backtest_detector(series, IQRDetector)
    summary = build_report(rows, tmp_path, title="t")
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "figures").is_dir()
    data = json.loads((tmp_path / "report.json").read_text())
    assert "summary" in data and "rows" in data
    assert "overall" in summary


def test_diff_reports_shows_metric_change(tmp_path):
    series = [generate_series("stationary", n=300, seed=80)]
    rows = backtest_detector(series, IQRDetector)
    build_report(rows, tmp_path / "a", title="a")
    build_report(rows, tmp_path / "b", title="b")
    md = diff_reports(tmp_path / "a" / "report.json", tmp_path / "b" / "report.json")
    assert "F1" in md or "f1" in md.lower()
