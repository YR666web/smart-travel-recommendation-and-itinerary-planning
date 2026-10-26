"""内容导入接口。"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.security import is_allowed_path
from app.services.import_service import get_task, import_document

router = APIRouter(tags=["import"])

_UPLOAD_DIR = "storage/uploads"


@router.post("/import")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """上传文档并触发导入。"""
    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    filename = os.path.basename(file.filename or "upload.md")
    if not filename.lower().endswith(".md"):
        raise HTTPException(status_code=400, detail="仅支持 Markdown 文件")
    saved_path = os.path.join(_UPLOAD_DIR, f"{uuid.uuid4().hex}-{filename}")
    if not is_allowed_path(saved_path):
        raise HTTPException(status_code=400, detail="非法文件路径")
    with open(saved_path, "wb") as f:
        size = 0
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > 10 * 1024 * 1024:
                f.close()
                os.unlink(saved_path)
                raise HTTPException(status_code=413, detail="文件不得超过 10 MB")
            f.write(chunk)

    try:
        task_id = import_document(saved_path, source_file=filename)
    except Exception:
        os.unlink(saved_path)
        raise
    task = get_task(task_id)
    if task and task["status"] == "failed":
        os.unlink(saved_path)
    return {"task_id": task_id}


@router.get("/import/tasks/{task_id}")
def get_import_task(task_id: int) -> dict:
    """查询导入任务状态。"""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task
