"""公开数据集（UCR 为主）的惰性下载与离线读取。

公开集只用于泛化验证，不用于调参。
UCR 单序列文件的真实 URL 形式仍未校准（见 docs/ROADMAP.md），因此在线下载
必须通过环境变量 ``ANOMALY_LAB_UCR_SERIES_URL`` 显式提供 URL 模板，例如::

    export ANOMALY_LAB_UCR_SERIES_URL='https://example.org/ucr/{name}.txt'

未提供模板时只读缓存；缓存缺失且离线则抛 ``DatasetUnavailable``。
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path

import numpy as np

from anomaly_lab.config import CONFIG
from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.data.synthetic import SYNTHETIC_EPOCH

UCR_BASE = "https://www.cs.ucr.edu/~eamonn/time_series_data_2018/"
_URL_ENV = "ANOMALY_LAB_UCR_SERIES_URL"
_OFFLINE_ENV = "ANOMALY_LAB_OFFLINE"


class DatasetUnavailable(RuntimeError):
    """公开集不可用（离线且无缓存，或下载失败）。"""


def _is_offline(offline: bool | None) -> bool:
    if offline is not None:
        return offline
    return os.environ.get(_OFFLINE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _cache_paths(name: str, cache_dir: Path) -> tuple[Path, Path, Path]:
    base = Path(cache_dir) / name
    return base, base / "values.txt", base / "meta.json"


def series_available(name: str, cache_dir: Path | None = None) -> bool:
    cache_dir = Path(cache_dir) if cache_dir is not None else CONFIG.public_cache_dir
    _, values_path, meta_path = _cache_paths(name, cache_dir)
    return values_path.is_file() and meta_path.is_file()


def _parse_values(path: Path) -> np.ndarray:
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        token = line.replace(",", " ").split()[0]
        try:
            values.append(float(token))
        except ValueError:
            continue
    if not values:
        raise DatasetUnavailable(f"无法从 {path} 解析出数值")
    return np.asarray(values, dtype=float)


def _make_timestamps(n: int, freq: str) -> np.ndarray:
    """等间隔时间戳。

    ⚠️ `np.arange(n) * delta` 的 dtype 是 `timedelta64[m]`，
    直接 `.astype("datetime64[ns]")` 会被 numpy **重新解释**（不做单位换算）——
    5 分钟变成 5 纳秒。先转 `timedelta64[ns]`（这一步会换算），再叠加到基准时刻。
    """
    digits = "".join(ch for ch in freq if ch.isdigit())
    unit = "".join(ch for ch in freq if ch.isalpha()).lower()
    mapping = {"min": "m", "m": "m", "h": "h", "s": "s", "d": "D"}
    step = int(digits) if digits else 1
    # mypy 把第二个参数收窄成 Literal，映射表的 str 类型对不上；运行时安全。
    delta = np.timedelta64(step, mapping.get(unit, "m")).astype("timedelta64[ns]")  # type: ignore[call-overload]
    return SYNTHETIC_EPOCH + np.arange(n) * delta


def _expand_intervals(intervals: list, n: int) -> np.ndarray:
    labels = np.zeros(n, dtype=np.int8)
    for item in intervals:
        if isinstance(item, dict):
            start, end = int(item["start"]), int(item["end"])
        else:
            start, end = int(item[0]), int(item[1])
        start = max(0, start)
        end = min(n - 1, end)
        if end >= start:
            labels[start : end + 1] = 1
    return labels


def _load_from_cache(name: str, cache_dir: Path) -> SeriesBundle:
    _, values_path, meta_path = _cache_paths(name, cache_dir)
    values = _parse_values(values_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    n = len(values)
    freq = str(meta.get("freq", "1min"))
    labels = _expand_intervals(meta.get("anomaly_intervals", []), n)
    return SeriesBundle(
        series_id=name,
        values=values,
        timestamps=_make_timestamps(n, freq),
        freq=freq,
        labels=labels,
        label_source="public",
        meta={**meta, "source": meta.get("source", "UCR"), "n": n},
    )


def _download_with_resume(url: str, dest: Path) -> None:
    """用 Range 头断点续传；失败抛 DatasetUnavailable。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            mode = "ab" if existing and response.status == 206 else "wb"
            if mode == "wb":
                existing = 0
            with dest.open(mode) as handle:
                handle.write(response.read())
    except Exception as exc:
        raise DatasetUnavailable(f"下载 {url} 失败: {exc}") from exc


def _download_series(name: str, cache_dir: Path) -> None:
    template = os.environ.get(_URL_ENV)
    if not template:
        raise DatasetUnavailable(
            "UCR 单序列 URL 未校准；请设置 "
            f"{_URL_ENV}（含 {{name}}）或先手动准备缓存目录"
        )
    base, values_path, meta_path = _cache_paths(name, cache_dir)
    url = template.format(name=name)
    _download_with_resume(url, values_path)
    raw = values_path.read_bytes()
    meta = {
        "source": url,
        "n": len(_parse_values(values_path)),
        "freq": "1min",
        "anomaly_intervals": [],
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    base.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def load_public_series(
    name: str,
    cache_dir: Path | None = None,
    offline: bool | None = None,
) -> SeriesBundle:
    cache_dir = Path(cache_dir) if cache_dir is not None else CONFIG.public_cache_dir
    if series_available(name, cache_dir):
        return _load_from_cache(name, cache_dir)
    if _is_offline(offline):
        raise DatasetUnavailable(f"离线模式且缓存缺失: {cache_dir / name}")
    _download_series(name, cache_dir)
    if not series_available(name, cache_dir):
        raise DatasetUnavailable(f"下载完成但缓存不完整: {cache_dir / name}")
    return _load_from_cache(name, cache_dir)
