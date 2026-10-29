"""全局配置：路径、默认参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SEED = 42


@dataclass
class Config:
    root: Path = field(default_factory=lambda: Path.cwd())
    data_dir: Path = field(default_factory=lambda: Path("data"))
    cache_dir: Path = field(default_factory=lambda: Path(".cache"))
    reports_dir: Path = field(default_factory=lambda: Path("reports"))
    seed: int = int(os.environ.get("ANOMALY_LAB_SEED", DEFAULT_SEED))

    @property
    def synthetic_dir(self) -> Path:
        return self.data_dir / "synthetic"

    @property
    def public_cache_dir(self) -> Path:
        return self.data_dir / "cache" / "public"

    @property
    def annotations_dir(self) -> Path:
        return self.data_dir / "annotations"

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.synthetic_dir,
            self.public_cache_dir,
            self.annotations_dir,
            self.reports_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


CONFIG = Config()
