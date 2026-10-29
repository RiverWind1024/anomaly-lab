import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors.base import VALID_SCORE_TYPES, validate_detector


def _series():
    return SeriesBundle(
        series_id="s",
        values=np.arange(100.0),
        timestamps=np.arange(100).astype("datetime64[ns]"),
        freq="1min",
    )


def test_valid_score_types_are_exactly_four():
    assert set(VALID_SCORE_TYPES) == {"zscore", "pvalue", "residual_ratio", "prob"}


def test_validate_detector_rejects_unknown_score_type():
    class Bad:
        name = "bad"
        score_type = "magic"

        def fit(self, s):
            return self

        def score(self, s):
            return np.zeros(len(s.values))

        def detect(self, s, threshold=None):
            raise NotImplementedError

    with pytest.raises(ValueError, match="score_type"):
        validate_detector(Bad())


def test_validate_detector_accepts_good_detector():
    class Good:
        name = "good"
        score_type = "zscore"

        def fit(self, s):
            return self

        def score(self, s):
            return np.zeros(len(s.values))

        def detect(self, s, threshold=None):
            raise NotImplementedError

    validate_detector(Good())
