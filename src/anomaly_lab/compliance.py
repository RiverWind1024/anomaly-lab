"""合规自检：扫描内部系统专名，防止把现职工作内容带进仓库。"""

from __future__ import annotations

from pathlib import Path

# 只禁内部系统专名；公开技术名词（Chronos 模型、Redis、Kafka 等）不在此列
FORBIDDEN_TERMS = [
    "Solaris",
    "Metis",
    "灯塔",
    "Prism",
    "Halley",
    "红盘",
    "呼呼",
    "Dify",
    "Jarvis",
    "KubeVirt",
    "Chaos",
]

_SCAN_FILES = ["README.md"]
_SCAN_DIRS = ["src", "tests", "notebooks", "docs"]
# 这些文件本身在讨论“哪些内部专名不能用”，必须豁免
_EXEMPT = {
    "src/anomaly_lab/compliance.py",
    "docs/RESEARCH.md",
    "docs/DESIGN.md",
    "docs/PLAN.md",
}


def scan_forbidden(text: str, terms: list[str]) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for term in terms:
            if term in line:
                hits.append((term, line_no))
    return hits


def scan_repo(root: Path | None = None, terms: list[str] | None = None) -> list[tuple[Path, str, int]]:
    root = Path(root or Path.cwd())
    terms = terms if terms is not None else FORBIDDEN_TERMS
    hits: list[tuple[Path, str, int]] = []
    targets: list[Path] = [root / name for name in _SCAN_FILES]
    for dirname in _SCAN_DIRS:
        base = root / dirname
        if base.exists():
            targets.extend(
                p
                for p in base.rglob("*")
                if p.is_file() and p.suffix in {".py", ".md", ".toml", ".sh", ".js", ".html", ".css"}
            )
    for path in targets:
        if not path.is_file():
            continue
        # 禁词表与讨论禁词的设计文档必须豁免，否则自检永远命中自己
        if path.resolve() in {(root / name).resolve() for name in _EXEMPT}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for term, line_no in scan_forbidden(text, terms):
            hits.append((path, term, line_no))
    return hits
