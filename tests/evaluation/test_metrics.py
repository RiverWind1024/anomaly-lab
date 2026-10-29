import numpy as np
import pytest

from anomaly_lab.evaluation.metrics import (
    detection_delay,
    interval_iou,
    point_adjusted_prf,
    precision_recall_f1,
    range_based_prf,
)


def test_perfect_prediction():
    truth = np.array([0, 0, 1, 1, 0], dtype=np.int8)
    p, r, f = precision_recall_f1(pred=truth, truth=truth)
    assert (p, r, f) == (1.0, 1.0, 1.0)


def test_point_adjusted_tolerates_delay():
    truth = np.array([0, 0, 0, 1, 1, 0], dtype=np.int8)
    pred = np.array([0, 0, 0, 0, 1, 0], dtype=np.int8)
    _p, r, _f = point_adjusted_prf(pred, truth, delay=2)
    assert r == pytest.approx(1.0)


def test_range_based_scores_overlap():
    pred = [(0, 4)]
    truth = [(0, 4)]
    _p, _r, f = range_based_prf(pred, truth)
    assert f == pytest.approx(1.0)


def test_range_based_penalizes_over_detection():
    pred = [(0, 9)]
    truth = [(0, 4)]
    p, _r, _f = range_based_prf(pred, truth)
    assert p < 1.0


def test_interval_iou():
    assert interval_iou((0, 10), (0, 10)) == pytest.approx(1.0)
    assert interval_iou((0, 10), (20, 30)) == pytest.approx(0.0)
    assert interval_iou((0, 10), (5, 15)) == pytest.approx(1 / 3)


def test_detection_delay():
    truth = np.array([0, 0, 1, 1], dtype=np.int8)
    pred = np.array([0, 0, 0, 1], dtype=np.int8)
    assert detection_delay(pred, truth) == 1
