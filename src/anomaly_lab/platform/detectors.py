"""平台层支持的检测器注册表与「自动推荐」。

只有能给出「基线 + 双向上下界」的算法才进入平台：前端要展示基线，
没有上下界的算法（如变点检验）留在离线评测里使用。

这些检测器的分数统一是「稳健 z 分数」量纲（偏离基线多少倍尺度），
所以同一套倍数规则可以跨检测器通用。

**例外是 Chronos**：它的分数是按序列 min-max 归一化到 [0,1] 的相对越界程度
（`score_type = "prob"`），不是「多少倍尺度」。因此：

- 它的告警阈值要用**绝对值条件**表达（`>=0.5, P1`），
  倍数条件 `0.5, P1` 在 [0,1] 分数上等价于「分数 ≥ 0.5」，也能用；
- 它没有 `bands()` 实现 → 预览图**不画基线与上下界带**（不是 bug，是它没有基线）；
- 它慢（约 2 秒/序列，统计检测器约 0.06 毫秒），定时任务要留足间隔。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from anomaly_lab.detectors.chronos import ChronosDetector
from anomaly_lab.detectors.statistical import (
    IQRDetector,
    MADDetector,
    SeasonalDetector,
    STLResidualDetector,
    TrendResidualIQRDetector,
    ZScoreDetector,
)
from anomaly_lab.detectors.trend import TheilSenTrendDetector

DETECTOR_FACTORIES = {
    "iqr": IQRDetector,
    "mad": MADDetector,
    "zscore": ZScoreDetector,
    "seasonal": SeasonalDetector,
    # period 传 None = 按序列自动估计周期（FFT + ACF）
    "stl_residual": STLResidualDetector,
    "trend_residual_iqr": TrendResidualIQRDetector,
    # 趋势型专用：Theil-Sen 稳健趋势线 + 残差 MAD（抗离群点）
    "theil_sen": TheilSenTrendDetector,
    # 预训练模型：可选依赖 + 需要本地权重，慢且没有基线
    "chronos": ChronosDetector,
}

#: **旧名 → 新名**（改名后旧名仍然可用）。
#:
#: ⚠️ 为什么需要：检测器名会进**历史数据**（评测产物、任务配置、告警记录），
#:    改名就等于让那些记录里的算法名变成「不认识的名字」——
#:    界面显示不出来，重跑也找不到对应算法。
#:
#: ⚠️ 别名**不出现在下拉清单里**（`detector_catalog` 只列主名）——
#:    否则用户会看到两个一模一样的选项。
#:    但历史评测产物里的旧名要能显示，所以前端另有标签映射。
DETECTOR_ALIASES = {
    # ⚠️ 旧名说的是「去季节化」，做的却是「去**趋势**」——名不副实。
    "deseasonalized_iqr": "trend_residual_iqr",
}

#: 慢算法（秒级/序列）—— 前端要提示用户留足执行间隔
SLOW_DETECTORS = frozenset({"chronos"})

#: **默认**参与离线评测与算法建议的检测器集合。
#:
#: ⚠️ 故意不含慢的预训练模型 —— 「遍历整个注册表」的地方（离线评测、
#:    算法建议的兜底列表）如果带上 Chronos，会把一次评测从几秒变成十几分钟，
#:    还会把慢算法塞进给用户的建议里。Chronos 要**显式点名**才跑。
DEFAULT_DETECTOR_SET = tuple(
    name for name in DETECTOR_FACTORIES if name not in SLOW_DETECTORS
)

#: 任务可以填 auto：运行时按序列形态自动推断检测器
AUTO_DETECTOR = "auto"

#: auto 推断不出可用候选时的兜底检测器（最通用）
DEFAULT_DETECTOR = "iqr"

#: 低于这个点数不做形态推断（特征不可靠）
MIN_AUTO_POINTS = 30

#: 分数量纲族 —— **告警阈值能不能跨算法沿用**，由它决定。
#:
#: ⚠️ `prob` 族（Chronos）的分数是序列内 min-max 归一化的**相对越界程度**，
#:    取值 [0, 1]；而统计族的分数是「偏离基线多少个尺度单位」，**没有上界**。
#:
#: ⚠️ 跨族沿用阈值 = **告警永远不触发** ——
#:    分数根本到不了 2.5，所以「一切正常」是假的。
#:    这是静默失效，比报错还糟。
SCORE_FAMILY_PROB = "prob"

#: 统计族：分数是「几个尺度单位」，阈值是倍数（2.5 / 3.5 …）。
SCORE_FAMILY_SCALE = "scale"


def detector_score_family(name: str) -> str:
    """检测器的分数量纲族。

    ⚠️ `auto` 归到统计族 —— 形态分类器的候选里没有 Chronos
       （慢、且没有基线带），所以 auto 永远落在统计族。
    """
    if name == AUTO_DETECTOR:
        return SCORE_FAMILY_SCALE
    try:
        detector = create_detector(name)
    except ValueError:
        return SCORE_FAMILY_SCALE
    return (
        SCORE_FAMILY_PROB
        if detector.score_type == "prob"
        else SCORE_FAMILY_SCALE
    )


@dataclass(frozen=True)
class DetectorResolution:
    """一条序列实际用了哪个检测器，以及为什么。

    `fallback` 表示没有按推荐结果走（推断不可靠或推荐的平台不支持），
    这种情况下 `rationale` 会说明原因，不静默降级。
    """

    detector: str
    requested: str
    metric_class: str | None = None
    confidence: float | None = None
    reasons: list[str] = field(default_factory=list)
    rationale: str = ""
    fallback: bool = False
    #: 形态分类给出的候选算法（按推荐顺序）；平台不支持的也在里面
    candidates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "detector": self.detector,
            "requested": self.requested,
            "metric_class": self.metric_class,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "rationale": self.rationale,
            "fallback": self.fallback,
            "candidates": list(self.candidates),
        }


def create_detector(name: str):
    """按名字造检测器。

    ⚠️ **旧名会被解析成新名** —— 见 `DETECTOR_ALIASES`。
       别名解析后造出来的对象，其 `name` 是**新名** ——
       所以检测结果里的 `detector` 字段不会因为用了旧名而分裂成两条记录。
    """
    name = DETECTOR_ALIASES.get(name, name)
    try:
        factory = DETECTOR_FACTORIES[name]
    except KeyError as exc:
        raise ValueError(f"不支持的检测器: {name}") from exc
    return factory()


def canonical_detector_name(name: str) -> str:
    """把旧名解析成新名（未知名原样返回）。

    ⚠️ 候选列表、可用性检查都要走这里 ——
       否则旧名会被判成「不支持的检测器」，
       而它其实只是**改过名**，历史数据里全是它。
    """
    return DETECTOR_ALIASES.get(name, name)


def detector_default_threshold(name: str) -> float:
    """取某个算法的**惯用阈值**（它的 `default_threshold`）。

    ⚠️ **`auto` 要落到兜底算法上** ——
       `auto` 本身不在注册表里（它在运行时才落到具体算法），
       但任务的阈值是按兜底算法的默认值预填的，
       所以这里必须用同一个算法（`DEFAULT_DETECTOR`）才算得对。
    """
    if name == AUTO_DETECTOR:
        name = DEFAULT_DETECTOR
    name = canonical_detector_name(name)
    try:
        return float(create_detector(name).default_threshold)
    except ValueError:
        # 未知算法：退回最通用的默认值
        return float(create_detector(DEFAULT_DETECTOR).default_threshold)


def resolve_detector(requested: str, series) -> DetectorResolution:
    """决定这条序列用哪个检测器。

    `requested` 是具体算法名时直接用它；是 `auto` 时按形态分类推荐，
    推荐里平台不支持的算法会被跳过——并如实记录，不静默换掉。
    """
    if requested != AUTO_DETECTOR:
        return DetectorResolution(detector=requested, requested=requested)
    n = len(series.values)
    if n < MIN_AUTO_POINTS:
        return DetectorResolution(
            detector=DEFAULT_DETECTOR,
            requested=requested,
            fallback=True,
            rationale=(
                f"点数 {n} 少于 {MIN_AUTO_POINTS}，形态推断不可靠，"
                f"用兜底算法 {DEFAULT_DETECTOR}"
            ),
        )
    # 延迟导入：分类器与检测器之间可能形成循环依赖
    from anomaly_lab.classification.classifier import classify

    result = classify(series)
    # ⚠️ 候选统一成**主名** —— 推荐表里写旧名时（历史配置）也要能解析
    candidates = [canonical_detector_name(name) for name in result.recommendation.detectors]
    supported = [name for name in candidates if name in DETECTOR_FACTORIES]
    unsupported = [name for name in candidates if name not in DETECTOR_FACTORIES]
    if supported:
        chosen = supported[0]
        fallback = False
    else:
        chosen = DEFAULT_DETECTOR
        fallback = True
    rationale = result.recommendation.rationale
    if unsupported:
        rationale = f"{rationale}；推荐中的 {'/'.join(unsupported)} 平台不支持"
    if fallback:
        rationale = f"{rationale}；无可用候选，回退到 {DEFAULT_DETECTOR}"
    return DetectorResolution(
        detector=chosen,
        requested=requested,
        metric_class=result.metric_class,
        confidence=result.confidence,
        reasons=list(result.reasons),
        rationale=rationale,
        fallback=fallback,
        candidates=candidates,
    )


def detector_available(name: str) -> tuple[bool, str | None]:
    """这个算法在当前环境能不能用？不可用时给出**人话**原因。

    统计检测器是纯 numpy/scipy，恒可用。只有 Chronos 需要探测：
    既要装了 `chronos` 包，又要有本地权重缓存（huggingface.co 不通时
    下载不下来，所以只认缓存）。

    `auto` 恒可用 —— 它在运行时才落到具体算法上。
    """
    if name == AUTO_DETECTOR:
        return True, None
    # ⚠️ 旧名要能用 —— 它只是**改过名**，不是不支持
    name = canonical_detector_name(name)
    if name not in DETECTOR_FACTORIES:
        return False, f"不支持的检测器: {name}"
    if name not in SLOW_DETECTORS:
        return True, None
    from anomaly_lab.detectors.chronos import chronos_available

    if chronos_available():
        return True, None
    return False, "chronos 未安装或本地无权重缓存（huggingface.co 不可达时不会自动下载）"


#: 检测器名 → 中文标签（给 API 消费者用）。
#:
#: ⚠️ 前端另有一份同源的映射（`frontend/src/lib/detectorLabels.ts`）——
#:    前端那份**多带旧名**（历史评测产物里还有），这份只有主名。
#:    两份要一起改。
DETECTOR_LABELS = {
    "iqr": "IQR 围栏",
    "mad": "MAD",
    "zscore": "Z 分数",
    "seasonal": "季节性分组",
    "stl_residual": "STL 残差",
    "trend_residual_iqr": "去趋势残差 IQR",
    "theil_sen": "稳健趋势线 Theil-Sen",
    "chronos": "Chronos 预训练模型",
}


def detector_catalog() -> list[dict]:
    """给前端用的检测器清单，含默认阈值与可用性。"""
    rows = [
        {
            "name": AUTO_DETECTOR,
            "default_threshold": float(
                create_detector(DEFAULT_DETECTOR).default_threshold
            ),
            "score_type": "auto",
            "label": "自动推荐（按形态推断）",
            "available": True,
            "reason": None,
            "slow": False,
        }
    ]
    for name in DETECTOR_FACTORIES:
        detector = create_detector(name)
        available, reason = detector_available(name)
        rows.append(
            {
                "name": name,
                "default_threshold": float(detector.default_threshold),
                "score_type": detector.score_type,
                "label": DETECTOR_LABELS.get(name, name),
                "available": available,
                "reason": reason,
                "slow": name in SLOW_DETECTORS,
            }
        )
    return rows
