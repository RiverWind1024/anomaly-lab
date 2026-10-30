#!/usr/bin/env python
"""下载 Chronos 权重到本地缓存（**唯一**允许联网的入口）。

为什么需要它：

huggingface.co 在本项目环境里不可达，而 `from_pretrained` 在网络不通时
会**重试退避 ~540 秒**才报错（实测首次加载 542 秒，真正装载只要 0.05 秒）。
所以运行期一律用 `local_files_only=True`（见 `detectors/chronos.py`），
权重必须**事先**下载好。

用法：

```bash
# 国内网络：走 hf-mirror 镜像
HF_ENDPOINT=https://hf-mirror.com .venv/bin/python scripts/download_chronos.py

# 指定模型（默认 amazon/chronos-t5-tiny）
ANOMALY_LAB_CHRONOS_MODEL=amazon/chronos-2 \\
  HF_ENDPOINT=https://hf-mirror.com .venv/bin/python scripts/download_chronos.py
```

下完之后离线校验：

```bash
.venv/bin/python -c "from anomaly_lab.detectors.chronos import chronos_available; print(chronos_available())"
```
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from anomaly_lab.detectors.chronos import default_model_name  # noqa: E402


def main() -> int:
    model_name = os.environ.get("ANOMALY_LAB_CHRONOS_MODEL", "").strip()
    if not model_name:
        print("用法：ANOMALY_LAB_CHRONOS_MODEL=amazon/chronos-2 python scripts/download_chronos.py")
        return 2

    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co")
    print(f"模型：{model_name}")
    print(f"端点：{endpoint}")

    try:
        from chronos import Chronos2Pipeline, ChronosPipeline
    except ImportError:
        print("chronos 包没装 —— 先 `uv pip install 'chronos-forecasting>=2.3'`", file=sys.stderr)
        return 1

    pipeline_class = (
        Chronos2Pipeline
        if "chronos-2" in model_name.lower() or "chronos2" in model_name.lower()
        else ChronosPipeline
    )
    print(f"用 {pipeline_class.__name__} 加载（联网模式，这一步可能几分钟）…")
    started = time.perf_counter()
    pipeline = pipeline_class.from_pretrained(model_name, device_map="cpu")
    print(f"✓ 加载完成，用时 {time.perf_counter() - started:.1f}s")

    from anomaly_lab.detectors.chronos import chronos_available

    print("本地缓存可用：", chronos_available(model_name))
    return 0 if chronos_available(model_name) else 1


if __name__ == "__main__":
    raise SystemExit(main())
