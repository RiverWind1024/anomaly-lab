import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.chronos import (
    ChronosDetector,
    ChronosUnavailable,
    chronos_available,
)


def _series():
    return SeriesBundle(
        series_id="s",
        values=np.sin(np.arange(200) / 10.0),
        timestamps=np.arange(200).astype("datetime64[ns]"),
        freq="1min",
    )


def test_chronos_available_returns_bool():
    assert isinstance(chronos_available(), bool)


def test_detector_raises_typed_error_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        "anomaly_lab.detectors.chronos.chronos_available", lambda: False
    )
    with pytest.raises(ChronosUnavailable):
        ChronosDetector().fit(_series())


def test_score_type_is_prob():
    assert ChronosDetector.score_type == "prob"
