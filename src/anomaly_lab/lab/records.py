"""P2：实验记录落盘 + 一键建任务草稿。

⚠️ **物理隔离** —— 实验产物只落在 `{data_root}/lab/experiments/`，
   永远不写 `reports/latest/`（那是 `make evaluate` 的地盘）。

⚠️ **可复现是硬要求** —— 记录里必须带上「将来能重跑出同样结果」的四件套：
   spec（参数 + seed）、env（git sha + 依赖版本）、result（结果）、fingerprint（指纹）。

   指纹**剔除耗时** —— 耗时每次都不同，它不该影响「两次是否一致」的判定。
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4

from anomaly_lab.frequency import freq_seconds
from anomaly_lab.lab.spec import DataSpec
from anomaly_lab.platform.timeutil import to_iso

#: 记录格式版本 —— 以后改结构时靠它区分旧记录。
EXPERIMENT_VERSION = 1

#: 记录里要记的依赖版本 —— 影响检测结果的那些。
_TRACKED_PACKAGES = ("numpy", "pandas", "scipy", "statsmodels")


def experiments_dir(data_root: Path) -> Path:
    """实验记录的落盘目录。"""
    return data_root / "lab" / "experiments"


# ---------- 环境快照 ----------


def _git(repo_root: Path, *args: str) -> str | None:
    """跑一条 git 命令；仓库不存在 / git 不可用时返回 None。"""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _repo_root() -> Path:
    """仓库根 —— `src/anomaly_lab/lab/records.py` 往上三层。"""
    return Path(__file__).resolve().parents[3]


def collect_env() -> dict[str, Any]:
    """环境快照：git 状态 + Python 版本 + 依赖版本。

    ⚠️ git 信息拿不到时返回 `None` 而不是编一个 —— 记录里必须如实说「不知道」。
    """
    root = _repo_root()
    sha = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")

    dependencies: dict[str, str | None] = {}
    for package in _TRACKED_PACKAGES:
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = None

    return {
        "git_sha": sha,
        "git_dirty": bool(status) if status is not None else None,
        "python": platform.python_version(),
        "dependencies": dependencies,
    }


# ---------- 指纹 ----------


def _strip_timing(value: Any) -> Any:
    """递归剔除耗时字段。

    ⚠️ 只有 `elapsed_ms` 是「每次都变但不影响结论」的量。
       剔除它，两次运行的指纹才能真正用来判断「结果是否一致」。
    """
    if isinstance(value, dict):
        return {
            key: (0 if key == "elapsed_ms" else _strip_timing(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_strip_timing(item) for item in value]
    return value


def result_fingerprint(result: dict[str, Any]) -> str:
    """结果指纹 —— 去掉耗时后取内容的 sha256。"""
    canonical = json.dumps(
        _strip_timing(result),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------- 记录 ----------


def _spec_payload(
    spec: DataSpec,
    *,
    detectors: list[str] | None,
    multipliers: list[float] | None,
    metric_name: str | None,
    freq: str | None = None,
) -> dict[str, Any]:
    """DataSpec 的完整可序列化视图（复现时要靠它，不能省字段）。"""
    return {
        "kind": spec.kind,
        "metric_id": spec.metric_id,
        "metric_name": metric_name,
        "source_id": spec.source_id,
        "sql": spec.sql,
        "time_column": spec.time_column,
        "value_column": spec.value_column,
        "group_column": spec.group_column,
        "time_format": spec.time_format,
        "source_timezone": spec.source_timezone,
        # ⚠️ 指标来源的 freq 是从指标继承的（spec 里是 None）——
        #    这里记**实际生效的**频率，否则将来复现时算不出执行间隔。
        "freq": freq or spec.freq,
        "missing_policy": spec.missing_policy,
        "max_series": spec.max_series,
        "start": to_iso(spec.start),
        "end": to_iso(spec.end),
        "sampling": {
            "mode": spec.sampling.mode,
            "window_points": spec.sampling.window_points,
            "stride_points": spec.sampling.stride_points,
            "max_points": spec.sampling.max_points,
            "max_windows": spec.sampling.max_windows,
            "min_valid_ratio": spec.sampling.min_valid_ratio,
            "seed": spec.sampling.seed,
        },
        "detectors": detectors,
        "multipliers": multipliers,
        # ⚠️ 真值与合成参数**必须一起记** —— 换了 seed 就换了数据，
        #    不记下来就复现不了。
        "truth": spec.truth,
        "synthetic": {
            "metric_class": spec.synthetic.metric_class,
            "n_points": spec.synthetic.n_points,
            "n_anomalies": spec.synthetic.n_anomalies,
            "anomaly_types": list(spec.synthetic.anomaly_types),
            "seed": spec.synthetic.seed,
        },
        "public": {
            "dataset": spec.public.dataset,
            "name": spec.public.name,
            "limit": spec.public.limit,
        },
    }


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    """列表页用的摘要 —— 只放「扫一眼就能判断」的东西。"""
    detectors = []
    for item in result.get("results", []):
        aggregate = item.get("aggregate", {})
        detectors.append(
            {
                "detector": item.get("detector"),
                "n_windows": aggregate.get("n_windows"),
                "n_alerts": aggregate.get("n_alerts"),
                "alert_ratio": aggregate.get("alert_ratio"),
                "stability": aggregate.get("stability"),
            }
        )
    return {
        "n_windows": len(result.get("windows", [])),
        "detectors": detectors,
        "warnings": result.get("warnings", []),
    }


def _new_id(created_at: datetime) -> str:
    """记录 id：时间戳 + 短随机后缀。

    ⚠️ 时间戳让记录天然按时间排序；随机后缀避免同一秒内两次保存撞名。
    """
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid4().hex[:6]}"


def save_experiment(
    data_root: Path,
    *,
    spec: DataSpec,
    result: dict[str, Any],
    detectors: list[str] | None = None,
    multipliers: list[float] | None = None,
    metric_name: str | None = None,
    freq: str | None = None,
    env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """保存一条实验记录，返回摘要（含 id）。"""
    created_at = datetime.now(UTC)
    record_id = _new_id(created_at)

    record = {
        "id": record_id,
        "version": EXPERIMENT_VERSION,
        # ⚠️ 这里用**微秒**精度 —— 平台的 `to_iso` 只到秒，
        #    同一秒内保存两条记录时列表排序就分不出先后了。
        "created_at": created_at.isoformat(),
        "spec": _spec_payload(
            spec,
            detectors=detectors,
            multipliers=multipliers,
            metric_name=metric_name,
            freq=freq,
        ),
        "env": env if env is not None else collect_env(),
        "result": result,
        "fingerprint": result_fingerprint(result),
    }

    directory = experiments_dir(data_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record_id}.json"
    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    return {
        "id": record_id,
        "created_at": record["created_at"],
        "version": record["version"],
        "fingerprint": record["fingerprint"],
        "spec": record["spec"],
        "env": record["env"],
        "summary": _summary(result),
    }


def _record_paths(data_root: Path) -> list[Path]:
    directory = experiments_dir(data_root)
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def list_experiments(data_root: Path) -> list[dict[str, Any]]:
    """实验记录列表 —— **新的在前**，每条只带摘要。"""
    items: list[dict[str, Any]] = []
    for path in _record_paths(data_root):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # 单个坏文件不该让整个列表挂掉
            continue
        items.append(
            {
                "id": record.get("id", path.stem),
                "created_at": record.get("created_at"),
                "fingerprint": record.get("fingerprint"),
                "spec": record.get("spec", {}),
                "summary": record.get("summary") or _summary(record.get("result", {})),
            }
        )
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return items


def load_experiment(data_root: Path, record_id: str) -> dict[str, Any]:
    """读一条完整记录。"""
    path = experiments_dir(data_root) / f"{record_id}.json"
    if not path.exists():
        raise ValueError(f"实验记录不存在: {record_id}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if "summary" not in record:
        record["summary"] = _summary(record.get("result", {}))
    return record


# ---------- 一键建任务 ----------


def _pick_detector(result: dict[str, Any]) -> tuple[str, list[str], str]:
    """从实验结果里挑一个算法进任务。

    ⚠️ 优先 `auto` —— 它逐窗自适应，实测随阈值变化最平缓。
       没有 auto 时，取「检出最多」的；并列时取更稳的（离散度小）。
    """
    runs = result.get("results", [])
    names = [str(item.get("detector")) for item in runs]

    if "auto" in names:
        chosen = "auto"
    elif runs:
        chosen = max(
            runs,
            key=lambda item: (
                item.get("aggregate", {}).get("n_alerts") or 0,
                -(item.get("aggregate", {}).get("stability") or 0.0),
            ),
        ).get("detector", "auto")
    else:
        chosen = "auto"

    alternatives = [name for name in names if name != chosen]
    return str(chosen), alternatives, _detector_rationale(result, str(chosen))


def _detector_rationale(result: dict[str, Any], chosen: str) -> str:
    run = next((item for item in result.get("results", []) if item.get("detector") == chosen), None)
    if run is None:
        return "实验里没有这个算法的结果，按平台默认走。"
    aggregate = run.get("aggregate", {})
    mix = aggregate.get("resolved_mix") or {}
    parts = [
        (
            f"实验里 {chosen} 检出 {aggregate.get('n_alerts', 0)} / {aggregate.get('n_points', 0)} 点"
            f"（检出率 {round(float(aggregate.get('alert_ratio') or 0) * 100, 2)}%）"
        )
    ]
    if mix:
        parts.append("实际用了 " + "、".join(f"{k}×{v}" for k, v in mix.items()))
    stability = aggregate.get("stability")
    if stability is not None:
        parts.append(f"跨窗检出率离散度 {stability}（越小越稳）")
    return "；".join(parts) + "。"


def build_job_draft(record: dict[str, Any]) -> dict[str, Any]:
    """从实验记录生成任务草稿（**只回填表单，不创建任务**）。

    ⚠️ 时间窗口必须与实验一致 —— 这是「实验所见 = 上线所得」的前提。
       实验记录里是「频率 × 窗口点数」，任务侧换算成秒。
    """
    spec = record.get("spec", {})
    result = record.get("result", {})

    if spec.get("kind") != "metric":
        raise ValueError("临时 SQL 的实验无法直接建任务 —— 请先把 SQL 固化成指标")

    metric_id = spec.get("metric_id")
    if not metric_id:
        raise ValueError("实验记录里没有 metric_id，无法建任务")

    # ⚠️ 优先用**实验结果里实际生效的**粒度 —— 指标来源的实验
    #    spec.freq 可能是 None（已从指标继承），result 里才记着真值。
    freq = str(result.get("freq") or spec.get("freq") or "")
    try:
        seconds_per_point = int(freq_seconds(freq)) if freq else 300
    except ValueError:
        seconds_per_point = 300

    window_points = int(spec.get("sampling", {}).get("window_points", 500))
    primary = float(result.get("primary_multiplier", 2.5))
    critical = round(primary * 1.5, 4)

    chosen, alternatives, rationale = _pick_detector(result)
    metric_name = spec.get("metric_name") or f"指标 {metric_id}"

    return {
        "metric_id": int(metric_id),
        "name": f"{metric_name} 巡检",
        "detector": chosen,
        "window_seconds": max(60, seconds_per_point * window_points),
        # 实验里频率同时用作「执行间隔」的默认值
        "interval_seconds": max(seconds_per_point, 10),
        "alert_threshold": primary,
        "critical_threshold": critical,
        "alert_rules": [
            {"level": "P1", "multiplier": primary},
            {"level": "P0", "multiplier": critical},
        ],
        "alternatives": alternatives,
        "rationale": rationale,
        "experiment_id": record.get("id"),
    }
