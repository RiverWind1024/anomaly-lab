"""NAB（Numenta Anomaly Benchmark）公开数据加载。

NAB 提供 58 个真实指标序列（AWS CloudWatch 等来源）与点级异常标签，
用来验证检测器与「自动推荐」在**真实数据**上的实际表现。

数据来自公开仓库 `numenta/NAB`，首次使用需要下载到缓存目录。
下载源可配置（``ANOMALY_LAB_NAB_URL``），因为公开仓库的直链在不同网络
环境下未必可达——这一点与 UCR 的处理方式一致（见 docs/ROADMAP.md）。
"""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from anomaly_lab.config import CONFIG
from anomaly_lab.contracts import SeriesBundle

#: NAB 仓库（公开数据集）
NAB_REPO = "numenta/NAB"

#: 默认下载源：整仓 tar 包（一次请求拿全，避免逐文件请求）
DEFAULT_NAB_URL = (
    "https://codeload.github.com/numenta/NAB/tar.gz/refs/heads/master"
)

_URL_ENV = "ANOMALY_LAB_NAB_URL"

#: NAB 的标签文件（点级异常标注）
_LABELS_FILE = "labels/combined_labels.json"

#: NAB 的真实数据目录（相对仓库根）
_VALUES_DIR = "data/realKnownValues"


class NabUnavailable(RuntimeError):
    """NAB 数据不可用（未下载且无法下载）。"""


def nab_cache_dir(cache_dir: Path | None = None) -> Path:
    base = Path(cache_dir) if cache_dir is not None else CONFIG.public_cache_dir
    return base / "nab"


def nab_available(cache_dir: Path | None = None) -> bool:
    """缓存里是否已有可用的 NAB 数据。"""
    root = nab_cache_dir(cache_dir)
    return (root / _LABELS_FILE).is_file() and (root / _VALUES_DIR).is_dir()


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "anomaly-lab"})
    with (
        urllib.request.urlopen(request, timeout=timeout) as response,
        dest.open("wb") as handle,
    ):
        shutil.copyfileobj(response, handle)


def download_nab(cache_dir: Path | None = None, url: str | None = None) -> Path:
    """下载并解包 NAB 到缓存目录，返回解包后的仓库根。"""
    root = nab_cache_dir(cache_dir)
    if nab_available(cache_dir):
        return root
    template = url or os.environ.get(_URL_ENV) or DEFAULT_NAB_URL
    archive = root / "nab.tar.gz"
    try:
        _download(template, archive)
    except Exception as exc:  # 网络问题统一转成可预期的异常
        raise NabUnavailable(f"下载 NAB 失败（{template}）: {exc}") from exc
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            prefixes = {member.name.split("/", 1)[0] for member in members if "/" in member.name}
            prefix = next(iter(prefixes), "")
            for member in members:
                if not member.name.startswith(f"{prefix}/"):
                    continue
                relative = member.name[len(prefix) + 1 :]
                if not relative or relative.startswith("."):
                    continue
                target = root / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        continue
                    with target.open("wb") as handle:
                        shutil.copyfileobj(extracted, handle)
    except Exception as exc:
        raise NabUnavailable(f"解包 NAB 失败: {exc}") from exc
    finally:
        archive.unlink(missing_ok=True)
    if not nab_available(cache_dir):
        raise NabUnavailable("NAB 解包后仍缺少标签或数据文件")
    return root


def _infer_freq(timestamps: pd.Series) -> str:
    """从相邻时间戳推断采样频率（分钟）。"""
    if len(timestamps) < 2:
        return "1min"
    deltas = timestamps.diff().dropna()
    minutes = float(deltas.dt.total_seconds().median() / 60)
    if minutes < 1:
        return "1min"
    if minutes >= 1440:
        return "1D"
    if minutes >= 60:
        return f"{round(minutes / 60)}h"
    return f"{round(minutes)}min"


def _load_labels(root: Path) -> dict[str, set[str]]:
    """点级标签：metric → 异常时间戳集合。"""
    payload = json.loads((root / _LABELS_FILE).read_text(encoding="utf-8"))
    labels: dict[str, set[str]] = {}
    for name, rows in payload.items():
        stamps = {
            str(row[0])
            for row in rows
            if isinstance(row, (list, tuple)) and len(row) >= 2 and row[2]
        }
        if stamps:
            labels[name] = stamps
    return labels


def load_nab_series(
    cache_dir: Path | None = None,
    limit: int | None = None,
    auto_download: bool = True,
) -> list[SeriesBundle]:
    """加载 NAB 的真实序列（带点级异常标签）。

    只保留**有异常标签且数据文件存在**的序列——没有标签的序列无法评估。
    """
    root = nab_cache_dir(cache_dir)
    if not nab_available(cache_dir):
        if not auto_download:
            raise NabUnavailable(f"NAB 数据未就绪: {root}")
        root = download_nab(cache_dir)
    labels = _load_labels(root)
    values_dir = root / _VALUES_DIR
    series_list: list[SeriesBundle] = []
    for name in sorted(labels):
        path = values_dir / Path(name).name
        if not path.is_file():
            continue
        frame = pd.read_csv(path)
        if "timestamp" not in frame.columns or "value" not in frame.columns:
            continue
        timestamps = pd.to_datetime(frame["timestamp"], errors="coerce")
        values = pd.to_numeric(frame["value"], errors="coerce")
        keep = timestamps.notna() & values.notna()
        timestamps = timestamps[keep]
        values = values[keep].to_numpy(dtype=float)
        if len(values) == 0:
            continue
        stamps = timestamps.dt.strftime("%Y-%m-%d %H:%M:%S")
        truth = np.array([stamp in labels[name] for stamp in stamps], dtype=np.int8)
        if truth.sum() == 0:
            continue
        series_list.append(
            SeriesBundle(
                series_id=Path(name).stem,
                values=values,
                timestamps=timestamps.to_numpy(dtype="datetime64[ns]"),
                freq=_infer_freq(timestamps),
                labels=truth,
                label_source="public",
                meta={"source": "NAB", "n": len(values)},
            )
        )
        if limit is not None and len(series_list) >= limit:
            break
    if not series_list:
        raise NabUnavailable(f"NAB 缓存里没有可用序列: {root}")
    return series_list
