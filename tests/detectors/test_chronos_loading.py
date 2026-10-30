"""Chronos 的加载路径：必须离线、模型名可配、类按模型分派。

⚠️ 这些测试**不碰真实权重** —— 用假的 pipeline 类替换掉，
只验证「我们怎么调用 from_pretrained」，不验证模型本身。
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pytest

from anomaly_lab.contracts import SeriesBundle
from anomaly_lab.detectors import chronos as chronos_module
from anomaly_lab.detectors.chronos import (
    ChronosDetector,
    ChronosUnavailable,
    default_model_name,
)


def _series() -> SeriesBundle:
    return SeriesBundle(
        series_id="s",
        values=np.sin(np.arange(200) / 10.0),
        timestamps=np.arange(200).astype("datetime64[ns]"),
        freq="1min",
    )


class _FakePipeline:
    """假装是 pipeline —— 只记录 from_pretrained 收到了什么参数。"""

    calls: ClassVar[list[dict]] = []

    @classmethod
    def from_pretrained(cls, model_name, **kwargs):
        cls.calls.append({"model_name": model_name, **kwargs})
        return cls()


def test_load_pipeline_uses_local_files_only(monkeypatch):
    """⚠️ 必须 `local_files_only=True`。

    huggingface.co 不可达时，`from_pretrained` 会重试退避 ~540 秒才报错
    （实测首次加载 542 秒，真正装载只要 0.05 秒）。进程级缓存救不了
    「服务重启后的第一次加载」。
    """
    _FakePipeline.calls = []
    monkeypatch.setattr(chronos_module, "_pipeline_class", lambda name: _FakePipeline)
    monkeypatch.setattr(chronos_module, "_PIPELINE_CACHE", {})

    chronos_module._load_pipeline("amazon/chronos-t5-tiny")

    call = _FakePipeline.calls[0]
    assert call["model_name"] == "amazon/chronos-t5-tiny"
    assert call.get("local_files_only") is True, "漏了 local_files_only 会卡 9 分钟"


def test_load_pipeline_failure_raises_typed_error(monkeypatch):
    """加载失败要抛 ChronosUnavailable，不能抛原始的网络异常。"""

    class _Boom:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            raise OSError("couldn't connect to huggingface.co")

    monkeypatch.setattr(chronos_module, "_pipeline_class", lambda name: _Boom)
    monkeypatch.setattr(chronos_module, "_PIPELINE_CACHE", {})

    # v1 路径
    with pytest.raises(ChronosUnavailable):
        chronos_module._load_pipeline("amazon/chronos-t5-tiny")


def test_chronos2_load_failure_raises_typed_error(monkeypatch):
    """Chronos-2 走自己的加载路径，失败也要抛同样的类型。"""
    monkeypatch.setattr(
        chronos_module,
        "_load_chronos2",
        lambda name: (_ for _ in ()).throw(OSError("no local weights")),
    )
    monkeypatch.setattr(chronos_module, "_PIPELINE_CACHE", {})

    with pytest.raises(ChronosUnavailable):
        chronos_module._load_pipeline("amazon/chronos-2")


def test_chronos2_uses_its_own_load_path(monkeypatch):
    """Chronos-2 **不能**走 `from_pretrained` —— 那条路会联网查 adapter。"""
    called: list[str] = []

    def _fake_load(model_name):
        called.append(model_name)
        return object()

    monkeypatch.setattr(chronos_module, "_load_chronos2", _fake_load)
    monkeypatch.setattr(chronos_module, "_PIPELINE_CACHE", {})

    chronos_module._load_pipeline("amazon/chronos-2")
    assert called == ["amazon/chronos-2"]


def test_pipeline_cache_avoids_reload(monkeypatch):
    """同进程内复用 pipeline —— 不重复装载权重。"""
    _FakePipeline.calls = []
    monkeypatch.setattr(chronos_module, "_pipeline_class", lambda name: _FakePipeline)
    monkeypatch.setattr(chronos_module, "_PIPELINE_CACHE", {})

    chronos_module._load_pipeline("amazon/chronos-t5-tiny")
    chronos_module._load_pipeline("amazon/chronos-t5-tiny")
    assert len(_FakePipeline.calls) == 1


def test_model_name_is_configurable(monkeypatch):
    """`ANOMALY_LAB_CHRONOS_MODEL` 能换模型。"""
    monkeypatch.setenv("ANOMALY_LAB_CHRONOS_MODEL", "amazon/chronos-2")
    assert default_model_name() == "amazon/chronos-2"
    assert ChronosDetector().model_name == "amazon/chronos-2"


def test_pipeline_class_dispatch():
    """Chronos-2 是另一个类 —— 选错类会加载失败。"""
    assert chronos_module._pipeline_class("amazon/chronos-2").__name__ == (
        "Chronos2Pipeline"
    )
    assert chronos_module._pipeline_class("amazon/chronos-t5-tiny").__name__ == (
        "ChronosPipeline"
    )


def test_cache_pattern_maps_model_name_to_dir():
    """模型名 → 本地缓存目录名。"""
    assert chronos_module._cache_pattern("amazon/chronos-2") == (
        "models--amazon--chronos-2"
    )
    assert chronos_module._cache_pattern("amazon/chronos-t5-tiny") == (
        "models--amazon--chronos-t5-tiny"
    )
