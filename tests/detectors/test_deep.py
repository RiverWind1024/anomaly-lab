import pytest

torch = pytest.importorskip("torch")

from anomaly_lab.data.synthetic import generate_series
from anomaly_lab.detectors.deep import TCNDetector, train_tcn


def test_tcn_training_reduces_loss(tmp_path):
    series = [
        generate_series("stationary", n=500, seed=90 + i, n_anomalies=0)
        for i in range(8)
    ]
    result = train_tcn(series, epochs=3, seed=1, out_path=tmp_path / "tcn.pt")
    assert result.history[-1] < result.history[0]


def test_tcn_detector_scores_higher_on_anomalies(tmp_path):
    s = generate_series(
        "stationary", n=500, seed=95, n_anomalies=1, anomaly_types=["spike"]
    )
    train_tcn(
        [
            generate_series("stationary", n=500, seed=100 + i, n_anomalies=0)
            for i in range(8)
        ],
        epochs=2,
        seed=1,
        out_path=tmp_path / "tcn.pt",
    )
    d = TCNDetector(model_path=tmp_path / "tcn.pt").fit(s)
    scores = d.score(s)
    truth = s.anomaly_indices()
    assert scores[truth].mean() > scores[~truth].mean()


def test_tcn_declares_prob_score_type(tmp_path):
    s = generate_series("stationary", n=300, seed=97, n_anomalies=0)
    train_tcn([s], epochs=1, seed=1, out_path=tmp_path / "tcn.pt")
    d = TCNDetector(model_path=tmp_path / "tcn.pt")
    assert d.score_type == "prob"


from anomaly_lab.detectors.deep import LSTMDetector, train_lstm


def test_lstm_training_reduces_loss(tmp_path):
    series = [
        generate_series("stationary", n=400, seed=120 + i, n_anomalies=0)
        for i in range(6)
    ]
    result = train_lstm(series, epochs=3, seed=1, out_path=tmp_path / "lstm.pt")
    assert result.history[-1] < result.history[0]


def test_lstm_scores_higher_on_anomalies(tmp_path):
    s = generate_series(
        "stationary", n=400, seed=125, n_anomalies=1, anomaly_types=["spike"]
    )
    train_lstm(
        [
            generate_series("stationary", n=400, seed=130 + i, n_anomalies=0)
            for i in range(6)
        ],
        epochs=2,
        seed=1,
        out_path=tmp_path / "lstm.pt",
    )
    d = LSTMDetector(model_path=tmp_path / "lstm.pt").fit(s)
    scores = d.score(s)
    truth = s.anomaly_indices()
    assert scores[truth].mean() > scores[~truth].mean()
