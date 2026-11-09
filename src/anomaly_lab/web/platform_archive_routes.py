"""归档数据集 API：创建 / 列表 / 归档检测记录 / 查看归档副本。

归档是**复制收藏**：原检测记录继续留在检测记录列表，归档目录里保存一份
独立的 npz 副本与元数据快照。原记录被删除或被保留策略清理后，归档仍可查看。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from anomaly_lab.platform import runner as runner_module
from anomaly_lab.platform.series_detail import build_series_detail
from anomaly_lab.platform.store import PlatformStore


class ArchiveSetIn(BaseModel):
    name: str
    description: str = ""


class ArchiveRecordIn(BaseModel):
    run_id: int
    series_id: str
    #: 用户填写的归档原因（可选）
    description: str = ""


def _archive_dir(data_root: Path, set_id: int) -> Path:
    return Path(data_root) / "archives" / f"set-{int(set_id)}"


def _file_name(run_id: int, series_id: str) -> str:
    """归档副本文件名 —— 用哈希避开 `:` 等路径非法字符。"""
    digest = hashlib.sha1(series_id.encode("utf-8")).hexdigest()[:12]
    return f"{int(run_id)}-{digest}.npz"


def _remove_file(data_root: Path, relative: str) -> None:
    """删除归档副本；只允许删 `archives/` 之内的文件。"""
    root = (Path(data_root) / "archives").resolve()
    target = (Path(data_root) / relative).resolve()
    if root not in target.parents:
        return
    target.unlink(missing_ok=True)


def build_archive_router(
    get_store: Callable[[], PlatformStore], get_data_root: Callable[[], Path]
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/platform/archives")
    def list_archive_sets() -> dict:
        return {"sets": get_store().list_archive_sets()}

    @router.post("/api/platform/archives")
    def create_archive_set(payload: ArchiveSetIn) -> dict:
        try:
            return get_store().create_archive_set(payload.name, payload.description)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/platform/archives/{set_id}")
    def delete_archive_set(set_id: int) -> dict:
        store = get_store()
        try:
            info = store.delete_archive_set(set_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # 整个数据集目录一起删（记录已级联删除）
        shutil.rmtree(_archive_dir(get_data_root(), set_id), ignore_errors=True)
        return {"deleted": {"archive_set_id": info["archive_set_id"]}}

    @router.get("/api/platform/archives/{set_id}")
    def archive_set_detail(set_id: int) -> dict:
        store = get_store()
        try:
            info = store.get_archive_set(set_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"set": info, "records": store.list_archive_records(set_id)}

    @router.post("/api/platform/archives/{set_id}/records")
    def archive_record(set_id: int, payload: ArchiveRecordIn) -> dict:
        store = get_store()
        data_root = get_data_root()
        try:
            record = store.get_detection_record(payload.run_id, payload.series_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        source_name = str(record.get("file") or "")
        if not source_name:
            raise HTTPException(status_code=400, detail="这条记录没有检测产物（数据不足）")
        source = runner_module.run_dir(data_root, payload.run_id) / source_name
        if not source.is_file():
            raise HTTPException(
                status_code=404,
                detail="检测产物文件缺失（可能已被保留策略清理），无法归档",
            )
        target_dir = _archive_dir(data_root, set_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / _file_name(payload.run_id, payload.series_id)
        shutil.copy2(source, target)
        relative = str(target.relative_to(data_root))
        try:
            return store.archive_detection(
                set_id,
                payload.run_id,
                payload.series_id,
                relative,
                payload.description,
            )
        except ValueError as exc:
            # 重复归档等 → 把刚复制出来的副本清掉，别留孤儿文件
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/platform/archives/{set_id}/records/{record_id}")
    def delete_archive_record(set_id: int, record_id: int) -> dict:
        store = get_store()
        try:
            info = store.delete_archive_record(record_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _remove_file(get_data_root(), str(info["file"]))
        return {"deleted": {"record_id": record_id}}

    @router.get("/api/platform/archive-records/{record_id}")
    def archive_record_detail(record_id: int) -> dict:
        """归档副本的完整时序 —— 结构与 `/api/runs/{run_id}/series/{series_id}` 一致。"""
        store = get_store()
        try:
            record = store.get_archive_record(record_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        path = Path(get_data_root()) / str(record["file"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="归档产物文件缺失")
        try:
            decision = json.loads(str(record["decision_json"] or "{}"))
        except json.JSONDecodeError:
            decision = {}
        return build_series_detail(
            path,
            run_id=int(record["run_id"]),
            series_id=str(record["series_id"]),
            decision=decision,
        )

    return router
