"""多算法对比：同一条序列用不同算法各跑一遍。"""

import numpy as np

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.platform.alerts import AlertRule, parse_rules
from anomaly_lab.platform.compare import compare_series


def _bundle(values: np.ndarray, freq: str = "5min") -> SeriesBundle:
    n = len(values)
    return SeriesBundle(
        series_id="s",
        values=np.asarray(values, dtype=float),
        timestamps=np.arange(n).astype("datetime64[ns]"),
        freq=freq,
    )


def _rules() -> list[AlertRule]:
    return parse_rules([{"multiplier": 1.0, "level": "P2"}, {"multiplier": 3.0, "level": "P1"}])


def test_compare_runs_every_requested_detector():
    values = np.sin(np.arange(200) / 12 * 2 * np.pi)
    outcomes = compare_series(_bundle(values), ["iqr", "seasonal"], _rules(), 1.0)
    assert [item.name for item in outcomes] == ["iqr", "seasonal"]
    for outcome in outcomes:
        assert len(outcome.scores) == len(values)
        assert len(outcome.severity) == len(values)
        assert outcome.baseline is not None
        assert outcome.lower is not None
        assert outcome.upper is not None


def test_compare_uses_the_same_rules_for_every_detector():
    """同一套倍数规则下，各算法的告警数可比。"""
    values = np.sin(np.arange(200) / 12 * 2 * np.pi)
    outcomes = compare_series(_bundle(values), ["iqr", "mad"], _rules(), 1.0)
    assert outcomes[0].n_alerts != outcomes[1].n_alerts
    for outcome in outcomes:
        assert set(np.unique(outcome.severity)).issubset({0, 1, 2})


def test_top_level_counts_the_highest_rule():
    """最高档计数按规则条数算，不能写死成 2（多档规则下会算错）。"""
    rng = np.random.default_rng(0)
    values = rng.normal(0, 1, 100)
    values[50] = 1000.0  # 极端尖峰 → 分数远超最高档倍数
    rules = parse_rules(
        [
            {"multiplier": 1.0, "level": "P2"},
            {"multiplier": 2.0, "level": "P1"},
            {"multiplier": 3.0, "level": "P0"},
        ]
    )
    outcome = compare_series(_bundle(values), ["iqr"], rules, 1.0)[0]
    assert outcome.n_alerts > 0
    # 最高档是第 3 档（索引 3），不是索引 2
    assert outcome.n_top == int((outcome.severity == 3).sum())
    assert outcome.n_top >= 1
    assert outcome.n_top <= outcome.n_alerts


def test_compare_reports_each_detector_default_threshold():
    """默认倍数是该算法「惯用」的倍数，用来解释分数量级差异。"""
    values = np.sin(np.arange(200) / 12 * 2 * np.pi)
    outcomes = compare_series(_bundle(values), ["iqr", "stl_residual"], _rules(), 1.0)
    defaults = {item.name: item.default_threshold for item in outcomes}
    assert defaults["iqr"] == 2.5
    assert defaults["stl_residual"] == 3.5
