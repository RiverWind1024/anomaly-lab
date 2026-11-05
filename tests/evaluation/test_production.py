"""生产检测记录的人工标注评估。

⚠️ 这一层的结论**只覆盖被标注过的那部分** —— 真值是人工标的，不是全集。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from anomaly_lab.evaluation.production import (
    OUTCOME_ALERT,
    OUTCOME_NORMAL,
    evaluate_production,
    list_candidates,
    list_samples,
)
from anomaly_lab.lab.truth import annotations_path
from anomaly_lab.platform.backfill import sync_run
from anomaly_lab.platform.store import PlatformStore

BASE_NS = int(np.datetime64("2026-01-01T00:00:00", "ns").astype("int64"))


def _store(tmp_path: Path) -> tuple[PlatformStore, int]:
    store = PlatformStore(tmp_path / "platform.db")
    source = store.add_source("生产源", str(tmp_path / "source.db"))
    metric = store.add_metric(
        source_id=source.id,
        name="生产指标",
        query="SELECT ts, value FROM t WHERE $timefilter",
        time_column="ts",
        value_column="value",
        freq="5min",
    )
    job = store.add_job(
        metric_id=metric.id,
        name="生产任务",
        detector="iqr",
        alert_threshold=2.5,
        critical_threshold=3.75,
        window_points=100,
        interval_seconds=300,
    )
    return store, job.id


def _make_run(
    store: PlatformStore,
    data_root: Path,
    *,
    job_id: int,
    series_id: str = "生产指标:web-api",
    n: int = 10,
    alerts: tuple[int, ...] = (3, 4),
    shift: int = 0,
) -> int:
    """造一次运行的产物（index.json + npz），并**同步进数据库**。

    ⚠️ `shift` 让窗口整体平移 —— 用来造「内容不同」的多次运行。
       不平移的话每次运行内容完全相同（滚动窗口的典型情况）。
    """
    # ⚠️ 必须先有 `runs` 行 —— `run_series.run_id` 有外键指向它。
    run_id = store.create_run(job_id).id
    target = data_root / "cache" / "platform" / "runs" / str(run_id)
    target.mkdir(parents=True, exist_ok=True)
    stamps = BASE_NS + (np.arange(n, dtype="int64") + shift) * 300_000_000_000
    severity = np.zeros(n, dtype=np.int16)
    for index in alerts:
        severity[index] = 1
    np.savez_compressed(
        target / "series.npz",
        timestamps=stamps,
        values=np.arange(n, dtype=float),
        scores=severity.astype(float),
        severity=severity,
        detector=np.array("iqr"),
        score_type=np.array("zscore"),
        levels=np.array(json.dumps(["正常", "P1", "P0"])),
    )
    (target / "index.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "job_id": job_id,
                "detector": "iqr",
                "generated_at": "2026-01-01T00:00:00+00:00",
                "n_insufficient": 0,
                "series": [
                    {
                        "series_id": series_id,
                        "group": "web-api",
                        "n": n,
                        "n_alerts": len(alerts),
                        "sufficient": True,
                        "detector": "iqr",
                        "file": "series.npz",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # ⚠️ 检测记录落库 —— 候选清单来自数据库，不再扫产物目录。
    sync_run(store, data_root, run_id)
    store.finish_run(run_id, "success", n_series=1, n_alerts=len(alerts))
    return run_id


def _annotate(
    data_root: Path,
    series_id: str,
    run_id: int,
    indices: list[int],
    rate: float | None = None,
    shift: int = 0,
) -> None:
    """按点位标一段（时间戳格式，与标注页一致）。

    ⚠️ **标注按序列存** —— 一条标注覆盖所有时间轴包含该时段的检测记录。
       `run_id` 只记进记录里做溯源。
    ⚠️ `rate` = 标这条时它所在层的采样率 —— 反算总体量时用它做权重。
    """
    path = annotations_path(data_root, series_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for index in indices:
        # ⚠️ 闭区间 —— start = end = 该点的时刻，正好覆盖一个点。
        start = end = str(
            np.datetime64(
                BASE_NS + (index + shift) * 300_000_000_000, "ns"
            ).astype("datetime64[s]")
        )
        lines.append(
            json.dumps(
                {
                    "series_id": series_id,
                    "start": start,
                    "end": end,
                    "type": "spike",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "run_id": run_id,
                    **({"rate": rate} if rate is not None else {}),
                },
                ensure_ascii=False,
            )
        )
    # ⚠️ **追加而不是覆盖** —— 标注按序列存，多次标注写同一个文件。
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _review(
    data_root: Path,
    series_id: str,
    run_id: int,
    rate: float | None = None,
) -> None:
    """「这条记录核对过」—— 不画区间，覆盖这次运行的整个窗口。"""
    path = annotations_path(data_root, series_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "series_id": series_id,
        "type": "reviewed",
        "run_id": run_id,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    if rate is not None:
        record["rate"] = rate
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_生产检测记录进清单(tmp_path):
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id)

    samples = list_samples(store, tmp_path)

    assert len(samples) == 1
    item = samples[0]
    assert item.run_id == 1
    assert item.series_id == "生产指标:web-api"
    assert item.source_name == "生产源"
    assert item.metric_name == "生产指标"
    assert item.n_alerts == 2
    assert item.n_annotations == 0


def test_候选来自数据库_不扫产物目录(tmp_path):
    """⚠️ 扫目录实测 8700 多个目录 = 0.47s，且随运行数线性涨。"""
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id)

    # 把产物目录删掉 —— 候选清单照样在（明细要读 npz，那是另一回事）。
    for path in (tmp_path / "cache" / "platform" / "runs" / "1").iterdir():
        path.unlink()

    assert len(list_candidates(store, tmp_path)) == 1


def test_标注与线上告警对比出F1(tmp_path):
    """线上报了 3、4 两点；人标了 3、4、5 → 命中 2、误报 0、漏报 1。"""
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3, 4))
    _annotate(tmp_path, "生产指标:web-api", 1, [3, 4, 5])

    result = evaluate_production(store, tmp_path)

    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["n_truth"] == 3
    assert row["n_pred"] == 2
    assert row["precision"] == 1.0
    assert row["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert row["f1"] == pytest.approx(0.8, abs=1e-3)


def test_按数据源指标与检出结果分层(tmp_path):
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id)
    _annotate(tmp_path, "生产指标:web-api", 1, [3])

    result = evaluate_production(store, tmp_path)

    assert len(result["layers"]) == 1
    layer = result["layers"][0]
    assert layer["source_name"] == "生产源"
    assert layer["metric_name"] == "生产指标"
    assert layer["outcome"] == OUTCOME_ALERT
    assert layer["n_candidates"] == 1
    assert layer["n_sampled"] == 1
    assert layer["n_annotated"] == 1
    assert result["overall"]["n_layers"] == 1


def test_正常记录单独成层(tmp_path):
    """⚠️ **正常层是估漏报的唯一来源** —— 没报告警的记录必须单独分层。"""
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))
    _make_run(store, tmp_path, job_id=job_id, alerts=(), shift=10)

    candidates = list_candidates(store, tmp_path)
    outcomes = {item.run_id: item.outcome for item in candidates}

    assert outcomes[1] == OUTCOME_ALERT
    assert outcomes[2] == OUTCOME_NORMAL

    result = evaluate_production(store, tmp_path)
    layers = {layer["outcome"] for layer in result["layers"]}
    assert layers == {OUTCOME_ALERT, OUTCOME_NORMAL}


def test_正常层与异常层用不同采样率(tmp_path):
    """⚠️ 正常记录远多于异常记录 —— 同一个采样率要么标不完，要么异常样本太少。"""
    store, job_id = _store(tmp_path)
    # 20 条异常（内容各不相同）+ 100 条正常
    for index in range(1, 21):
        _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=index)
    for index in range(21, 121):
        _make_run(store, tmp_path, job_id=job_id, alerts=(), shift=index)

    result = evaluate_production(
        store, tmp_path, rate_alert=1.0, rate_normal=0.1, max_per_layer=None
    )

    layers = {layer["outcome"]: layer for layer in result["layers"]}
    # 异常层全抽（20 条）
    assert layers[OUTCOME_ALERT]["n_sampled"] == 20
    # 正常层抽 10%
    assert layers[OUTCOME_NORMAL]["n_sampled"] == 10
    assert result["sampling"]["rate_alert"] == 1.0
    assert result["sampling"]["rate_normal"] == 0.1


def test_内容相同也各算一条检测记录(tmp_path):
    """⚠️ **活数据源每次检测的内容都不同** —— 抽样单位就是「一条检测记录」。

    静态数据源 / 手动重跑才会出现内容相同的情况；
    那时 `n_contents` 会把差异显示出来，而不是偷偷去重。
    """
    store, job_id = _store(tmp_path)
    for _ in range(5):
        _make_run(store, tmp_path, job_id=job_id, alerts=(3,))

    result = evaluate_production(store, tmp_path, rate_alert=1.0, max_per_layer=None)

    layer = result["layers"][0]
    assert layer["n_candidates"] == 5
    # ⚠️ 5 条记录，内容只有 1 种（静态源 / 重跑）—— 差异要看得见
    assert layer["n_contents"] == 1
    assert layer["n_sampled"] == 5


def test_内容不同的检测各算一条(tmp_path):
    """活数据源的常态：每次窗口都在动 → 每次检测都不同。"""
    store, job_id = _store(tmp_path)
    for index in range(1, 6):
        _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=index)

    result = evaluate_production(store, tmp_path, rate_alert=1.0, max_per_layer=None)

    layer = result["layers"][0]
    assert layer["n_candidates"] == 5
    assert layer["n_contents"] == 5


def test_告警事件数与检测记录数分开报(tmp_path):
    """⚠️ **同一个异常区间会被连续多次运行反复报出** ——
    尖峰在滑出窗口前一直被报，那在用户看来是**一个**告警。

    检测记录数（5）与告警事件数（1）必须分开报，
    否则「5」会被读成「5 个异常」。
    """
    store, job_id = _store(tmp_path)
    for _ in range(5):
        _make_run(store, tmp_path, job_id=job_id, alerts=(3,))

    result = evaluate_production(store, tmp_path, rate_alert=1.0, max_per_layer=None)

    layer = result["layers"][0]
    assert layer["n_candidates"] == 5
    assert layer["n_events"] == 1
    assert result["sampling"]["n_events"] == 1


def test_正常层没有告警事件(tmp_path):
    """⚠️ 正常记录**什么都没报** —— 它的告警事件数必须是 0。

    同一条序列既有报出告警的记录，也有什么都没报的记录，
    两层的告警事件数不能串。
    """
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))
    _make_run(store, tmp_path, job_id=job_id, alerts=(), shift=10)

    result = evaluate_production(store, tmp_path)

    layers = {layer["outcome"]: layer for layer in result["layers"]}
    assert layers[OUTCOME_ALERT]["n_events"] == 1
    assert layers[OUTCOME_NORMAL]["n_events"] == 0


def test_只标异常区间_其余告警点不算误报(tmp_path):
    """⚠️ **标注只覆盖窗口一小段时，其余时段的告警不能算误报** ——
    用户根本没看过那些时刻。

    这是「凭空多出 23 个误报」那个 bug 的回归测试。
    """
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3, 7))
    # 只标了第 3 点，没声明整条记录核对过
    _annotate(tmp_path, "生产指标:web-api", 1, [3])

    result = evaluate_production(store, tmp_path)

    row = result["rows"][0]
    assert row["tp"] == 1
    # ⚠️ 第 7 点没被核对过 → 不算误报（如果算，precision 会被凭空压低）
    assert row["fp"] == 0
    assert row["precision"] == 1.0
    assert row["n_scored_points"] == 1


def test_整条记录核对过_窗口内的告警都算误报(tmp_path):
    """⚠️ 用户声明「这条记录核对过」之后，窗口里没标成异常的告警才是误报。"""
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3, 7))
    _annotate(tmp_path, "生产指标:web-api", 1, [3])
    _review(tmp_path, "生产指标:web-api", 1)

    result = evaluate_production(store, tmp_path)

    row = result["rows"][0]
    assert row["tp"] == 1
    assert row["fp"] == 1
    assert row["n_scored_points"] == 10


def test_整条记录正常_没有异常也要进统计(tmp_path):
    """⚠️ **负样本标签** —— 用户确认整条记录正常，这就是 Recall 的分母来源。

    没有它，评估只能把「没标的地方」当正常，漏报永远测不出来。
    """
    store, job_id = _store(tmp_path)
    # 线上报了一个点，但用户核对了整条记录后说「这里没有异常」
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))
    _review(tmp_path, "生产指标:web-api", 1)

    result = evaluate_production(store, tmp_path)

    row = result["rows"][0]
    assert row["n_truth"] == 0
    assert row["n_annotations"] == 0
    assert row["tp"] == 0
    # ⚠️ 核对了、没标异常 → 那个告警点是误报
    assert row["fp"] == 1
    assert row["precision"] == 0.0


def test_待标用核对状态判断而不是有没有异常区间(tmp_path):
    """⚠️ 核对过一条**正常**记录，它也应当从待办队列里消失。"""
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))

    assert list_samples(store, tmp_path, todo_only=True, rate_alert=1.0, max_per_layer=None)
    _review(tmp_path, "生产指标:web-api", 1)
    assert not list_samples(store, tmp_path, todo_only=True, rate_alert=1.0, max_per_layer=None)


def test_采样率决定每层抽多少(tmp_path):
    """⚠️ 候选太多标不完 —— 采样率就是给人看的「标这么多够不够」。"""
    store, job_id = _store(tmp_path)
    for index in range(1, 11):
        _make_run(store, tmp_path, job_id=job_id, shift=index)

    result = evaluate_production(store, tmp_path, rate_alert=0.2, max_per_layer=None)

    sampling = result["sampling"]
    assert sampling["n_candidates"] == 10
    assert sampling["n_sampled"] == 2
    assert sampling["rate_alert"] == 0.2


def test_采样是确定性的_标过的不白标(tmp_path):
    """⚠️ 随机抽样每次结果都不同 —— 用户标过的记录下次就不在样本里了。"""
    store, job_id = _store(tmp_path)
    for index in range(1, 11):
        _make_run(store, tmp_path, job_id=job_id, shift=index)

    first = evaluate_production(store, tmp_path, rate_alert=0.5, max_per_layer=None)
    second = evaluate_production(store, tmp_path, rate_alert=0.5, max_per_layer=None)

    assert [row["run_id"] for row in first["rows"]] == [
        row["run_id"] for row in second["rows"]
    ]


def test_等间隔抽样覆盖整段时间(tmp_path):
    """⚠️ 只抽到某一段的话，那段时间之外的问题就看不见了。"""
    store, job_id = _store(tmp_path)
    for index in range(1, 11):
        _make_run(store, tmp_path, job_id=job_id, shift=index)

    samples = list_samples(store, tmp_path, rate_alert=0.2, max_per_layer=None)

    run_ids = [item.run_id for item in samples]
    assert min(run_ids) == 1
    assert max(run_ids) == 10


def test_没有标注就说清楚(tmp_path):
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id)

    result = evaluate_production(store, tmp_path)

    assert result["rows"] == []
    assert result["sampling"]["n_sampled"] == 1
    assert result["sampling"]["n_annotated"] == 0
    assert any("没有" in text or "还没" in text for text in result["warnings"])


def test_正常层没标就说Recall不可信(tmp_path):
    """⚠️ 漏报只有在正常记录里才看得见 —— 没标正常层要说出来。"""
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))
    _make_run(store, tmp_path, job_id=job_id, alerts=(), shift=10)

    result = evaluate_production(store, tmp_path)

    assert any("Recall" in text for text in result["warnings"])


def test_标注按序列存_只覆盖时间轴内的检测记录(tmp_path):
    """⚠️ **一条标注覆盖所有含该时段的检测记录** —— 不用重复标。

    run 1 的窗口是 [0, 9]，run 2 的窗口是 [10, 19] —— 不重叠，
    所以 run 1 的标注影响不到 run 2。
    """
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))
    _make_run(store, tmp_path, job_id=job_id, alerts=(7,), shift=10)
    _annotate(tmp_path, "生产指标:web-api", 1, [3])

    samples = list_samples(store, tmp_path, rate_alert=1.0, max_per_layer=None)
    annotated = {item.run_id: item.n_annotations for item in samples}

    assert annotated[1] == 1
    # ⚠️ run 2 的窗口里没有这段标注 —— 不能算到它头上。
    assert annotated[2] == 0


def test_一次标注复用给多次重叠的检测(tmp_path):
    """⚠️ **滚动窗口的常态** —— 同一个异常被连续多次运行报出，
    标一次就该被所有覆盖它的检测记录复用，而不是要求标几十次。
    """
    store, job_id = _store(tmp_path)
    # 三次运行：run 1 窗口 [0,9]、run 2 [5,14]、run 3 [10,19]
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=5)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=10)
    # 只标一次（run 1 的第 3 点 = 全局时刻 3）
    _annotate(tmp_path, "生产指标:web-api", 1, [3])

    samples = list_samples(store, tmp_path, rate_alert=1.0, max_per_layer=None)
    annotated = {item.run_id: item.n_annotations for item in samples}

    # run 1 覆盖时刻 3；run 2 窗口 [5,14] 不覆盖；run 3 也不覆盖。
    assert annotated[1] == 1
    assert annotated[2] == 0
    assert annotated[3] == 0

    # 再标一段落在 run 2 与 run 3 重叠区的（时刻 12）
    _annotate(tmp_path, "生产指标:web-api", 1, [12])
    samples = list_samples(store, tmp_path, rate_alert=1.0, max_per_layer=None)
    annotated = {item.run_id: item.n_annotations for item in samples}
    # ⚠️ run 2 的窗口 [5,14] 与 run 3 的 [10,19] 都覆盖时刻 12 → 一次标注两处生效
    assert annotated[2] == 1
    assert annotated[3] == 1


def test_没有标注覆盖的窗口不进统计(tmp_path):
    """⚠️ 时间轴里一段标注都没有 → 没有真值可比，进了统计会把「没标」当成「全对」。"""
    store, job_id = _store(tmp_path)
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,))
    _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=100)
    _annotate(tmp_path, "生产指标:web-api", 1, [3])

    result = evaluate_production(store, tmp_path, rate_alert=1.0, max_per_layer=None)

    assert [row["run_id"] for row in result["rows"]] == [1]


def test_反算按各自的采样率加权(tmp_path):
    """⚠️ **比率不能平均** —— 必须先按权重加总计数，再算比率。

    一条 20% 采样率抽中的记录代表总体里的 5 条，
    它的命中要按 5 倍算进总体。
    """
    store, job_id = _store(tmp_path)
    # ⚠️ 窗口**不重叠**（shift 隔 100）—— 每条检测记录各管一段，
    #    这样权重算术才是干净的 2.5 与 1。
    for index in range(1, 6):
        _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=index * 100)
    # ⚠️ run 1 被抽中（rate 2/5 = 0.4 → 权重 2.5），标注命中
    _annotate(tmp_path, "生产指标:web-api", 1, [3], rate=0.4, shift=100)
    # ⚠️ run 3 整条记录核对过（rate=1 → 权重 1），并在没告警的地方标了异常
    #    → 窗口里那个告警点是**误报**，标注的点是**漏报**
    _review(tmp_path, "生产指标:web-api", 3, rate=1.0)
    _annotate(tmp_path, "生产指标:web-api", 3, [9], rate=1.0, shift=300)

    result = evaluate_production(store, tmp_path, rate_alert=0.4, max_per_layer=None)

    overall = result["overall"]
    # 加权：TP = 2.5×1 + 1×0 = 2.5；FP = 2.5×0 + 1×1 = 1；FN = 0 + 1 = 1
    assert overall["precision"] == pytest.approx(2.5 / 3.5, abs=1e-3)
    assert overall["recall"] == pytest.approx(2.5 / 3.5, abs=1e-3)
    # ⚠️ 不加权的话是 0.5 / 0.5 —— 加权确实起作用了。
    assert overall["precision"] != pytest.approx(0.5, abs=1e-3)


def test_评估用所有已标注的_不限于当前采样(tmp_path):
    """⚠️ 标注是稀缺资源 —— 标过的都要用上，反算靠权重而不是靠「抽没抽中」。"""
    store, job_id = _store(tmp_path)
    for index in range(1, 6):
        _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=index * 100)
    # ⚠️ 标了一个当前采样**不会**抽中的 run（窗口不重叠，只影响它自己）
    _annotate(tmp_path, "生产指标:web-api", 3, [3], rate=0.2, shift=300)

    result = evaluate_production(store, tmp_path, rate_alert=0.4, max_per_layer=None)

    assert result["sampling"]["n_sampled"] == 2
    # ⚠️ 但它照样参与反算 —— 权重由它自己的 rate 决定。
    assert len(result["rows"]) == 1
    assert result["rows"][0]["run_id"] == 3
    assert result["rows"][0]["rate"] == 0.2
    assert result["rows"][0]["weight"] == 5.0


def test_一条标注覆盖多条重叠检测_权重各算各的(tmp_path):
    """⚠️ 一次标注被 5 条重叠的检测记录复用 —— 每条按自己的采样率反算。

    这正是滚动窗口的常态：标一次，5 条记录都算数。
    """
    store, job_id = _store(tmp_path)
    for index in range(5):
        _make_run(store, tmp_path, job_id=job_id, alerts=(3,), shift=index)
    # 时刻 3 落在前 4 条窗口里（[0,9] ~ [3,12]），第 5 条窗口 [4,13] 不含它
    _annotate(tmp_path, "生产指标:web-api", 1, [3], rate=0.4)

    result = evaluate_production(store, tmp_path, rate_alert=0.4, max_per_layer=None)

    assert len(result["rows"]) == 4
    assert {row["rate"] for row in result["rows"]} == {0.4}
    # ⚠️ 只有窗口起点那次报对了（告警点落在标注时刻）——
    #    后三次的告警点在更晚的时刻，被同一段标注判成**漏报**。
    assert result["overall"]["tp"] == pytest.approx(2.5, abs=1e-4)
    assert result["overall"]["fn"] == pytest.approx(7.5, abs=1e-4)
    assert result["overall"]["recall"] == pytest.approx(0.25, abs=1e-4)
