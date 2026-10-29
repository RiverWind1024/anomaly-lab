from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.evaluation.compare import compare_detectors


def test_compare_returns_rows_for_available_detectors():
    series = [
        generate_series(c, n=300, seed=110 + i)
        for i, c in enumerate(["stationary", "periodic", "trending"])
    ]
    rows = compare_detectors(
        series,
        [
            ("IQR", "anomaly_lab.detectors.statistical", "IQRDetector"),
            ("MAD", "anomaly_lab.detectors.statistical", "MADDetector"),
        ],
    )
    assert len(rows) >= 3
    for r in rows:
        assert r.detector in {"IQR", "MAD"}
        assert r.skipped_reason is None


def test_compare_records_skipped_reason_for_unavailable():
    series = [generate_series("stationary", n=200, seed=115)]
    rows = compare_detectors(
        series,
        [("Chronos", "anomaly_lab.detectors.chronos", "ChronosDetector")],
    )
    assert any(r.skipped_reason for r in rows)
