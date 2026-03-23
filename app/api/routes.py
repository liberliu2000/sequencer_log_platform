from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.settings import get_settings
from app.repositories.task_repository import TaskRepository
from app.schemas.common import DashboardSummary, UploadTaskResponse
from app.services.config_service import ConfigService
from app.services.export_service import ExportService
from app.services.ingestion_service import IngestionService
from app.services.llm_service import LLMService
from app.services.prompt_template_service import PromptTemplateService
from app.services.query_service import QueryService
from app.services.task_queue import queue

router = APIRouter()


def _dt_text(v):
    return v.isoformat() if hasattr(v, "isoformat") else str(v or "")


@router.get("/health")
def health():
    return {"status": "ok", "queue_pending": len(queue.pending)}


@router.post("/tasks/upload", response_model=UploadTaskResponse)
async def upload_logs(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    settings = get_settings()
    repo = TaskRepository(db)
    task_uuid = uuid.uuid4().hex
    batch_dir = Path(settings.upload_dir) / task_uuid
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved_count = 0
    total_bytes = 0
    for upload in files:
        safe_name = Path(upload.filename or f"upload_{saved_count+1}").name
        out_path = batch_dir / safe_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("wb") as f:
            while True:
                chunk = await upload.read(settings.chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                total_bytes += len(chunk)
        await upload.close()
        saved_count += 1

    display_name = files[0].filename if len(files) == 1 else f"batch_{saved_count}files"
    task = repo.create_task(task_uuid=task_uuid, filename=display_name or f"batch_{saved_count}files", stored_path=str(batch_dir))
    repo.update_task_progress(task.id, status="queued", current_stage="等待异步任务队列调度", file_count=saved_count, message=f"批量上传完成，共 {saved_count} 个文件，{round(total_bytes / 1024 / 1024, 2)} MB")
    position = queue.submit(task_uuid, lambda: IngestionService.process_task_by_uuid(task_uuid))
    repo.update_task_progress(task.id, status="queued", current_stage="等待异步任务队列调度", queue_position=position, file_count=saved_count, message=f"已进入队列，第 {position} 位")
    repo.add_audit_log(task.id, task_uuid, "queued", "info", "异步队列", f"queue_position={position}, files={saved_count}, bytes={total_bytes}")
    return UploadTaskResponse(task_uuid=task.task_uuid, filename=task.filename, status=task.status, file_count=task.file_count, total_events=task.total_events, total_errors=task.total_errors, message=task.message)


@router.get("/tasks/overview")
def tasks_overview(db: Session = Depends(get_db)):
    return TaskRepository(db).get_task_overview()


@router.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    repo = TaskRepository(db)
    return [{"task_uuid": t.task_uuid, "filename": t.filename, "status": t.status, "file_count": t.file_count, "total_events": t.total_events, "total_errors": t.total_errors, "progress_percent": t.progress_percent, "current_stage": t.current_stage, "queue_position": t.queue_position, "message": t.message, "created_at": _dt_text(t.created_at), "updated_at": _dt_text(t.updated_at)} for t in repo.list_tasks()]


@router.get("/tasks/{task_uuid}/status")
def task_status(task_uuid: str, db: Session = Depends(get_db)):
    task = TaskRepository(db).get_task_by_uuid(task_uuid)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task_uuid": task.task_uuid, "filename": task.filename, "status": task.status, "file_count": task.file_count, "total_events": task.total_events, "total_errors": task.total_errors, "progress_percent": task.progress_percent, "current_stage": task.current_stage, "queue_position": task.queue_position or queue.queue_position(task.task_uuid), "message": task.message, "created_at": _dt_text(task.created_at), "updated_at": _dt_text(task.updated_at)}


@router.get("/tasks/{task_uuid}/dashboard", response_model=DashboardSummary)
def dashboard(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_dashboard(task.id)


@router.get("/tasks/{task_uuid}/events")
def events(task_uuid: str, component: str | None = None, level: str | None = None, cycle_no: int | None = None, chip_name: str | None = None, search: str | None = None, limit: int = Query(default=500, le=5000), db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.list_events(task.id, component, level, cycle_no, chip_name, search, limit)


@router.get("/tasks/{task_uuid}/cycles")
def list_cycles(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.list_cycles(task.id)


@router.get("/tasks/{task_uuid}/steps")
def step_summaries(task_uuid: str, cycle_no: int | None = None, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_step_summaries(task.id, cycle_no=cycle_no)


@router.get("/tasks/{task_uuid}/cycle-summary")
def cycle_summary(task_uuid: str, unit: str = Query(default="ms"), db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_cycle_summaries(task.id, unit=unit)


@router.get("/tasks/{task_uuid}/movement-timeline")
def movement_timeline(task_uuid: str, cycle_no: int | None = None, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_movement_timeline(task.id, cycle_no=cycle_no)


@router.get("/tasks/{task_uuid}/operational-metrics")
def operational_metrics(task_uuid: str, cycle_no: int | None = None, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_operational_metrics(task.id, cycle_no=cycle_no)


@router.get("/tasks/{task_uuid}/errors")
def error_clusters(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_error_clusters(task.id)


@router.get("/tasks/{task_uuid}/errors/trend")
def error_trend(task_uuid: str, signature: str | None = None, family: str | None = None, bucket: str = Query(default="day"), db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_error_regression_trend(task.id, signature=signature, family=family, bucket=bucket)


@router.post("/tasks/{task_uuid}/errors/{signature}/analyze")
def analyze_signature(task_uuid: str, signature: str, force: bool = Query(default=False), db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return LLMService(db).analyze_signature(task.id, signature, force=force)


@router.get("/tasks/{task_uuid}/llm-results")
def list_llm_results(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return LLMService(db).list_results(task.id)


@router.get("/tasks/{task_uuid}/audit-logs")
def audit_logs(task_uuid: str, limit: int = 200, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.get_audit_logs(task.id, limit=limit)


@router.get("/tasks/{task_uuid}/files")
def task_files(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.list_task_files(task.id)


@router.get("/tasks/{task_uuid}/files/preview")
def preview_file(task_uuid: str, relative_path: str, max_lines: int = 200, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); return query.preview_task_file(task.id, relative_path, max_lines=max_lines)


@router.get("/config")
def get_config():
    return ConfigService().get_all()


@router.put("/config/thresholds")
def update_thresholds(payload: dict):
    return ConfigService().update_thresholds(payload)


@router.get("/config/prompt-templates")
def get_prompt_templates():
    return PromptTemplateService().get_templates()


@router.put("/config/prompt-templates/active")
def set_active_prompt_template(payload: dict):
    version = payload.get("version")
    if not version:
        raise HTTPException(status_code=400, detail="缺少 version")
    return PromptTemplateService().set_active_version(version)


@router.get("/tasks/{task_uuid}/export/events")
def export_events(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); path = ExportService(db).export_events_csv(task.id, task_uuid); return FileResponse(path=path, filename=Path(path).name)


@router.get("/tasks/{task_uuid}/export/errors")
def export_errors(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); path = ExportService(db).export_error_report_csv(task.id, task_uuid); return FileResponse(path=path, filename=Path(path).name)


@router.get("/tasks/{task_uuid}/export/report.json")
def export_report_json(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); path = ExportService(db).export_json_report(task.id, task_uuid); return FileResponse(path=path, filename=Path(path).name)


@router.get("/tasks/{task_uuid}/export/report.xlsx")
def export_report_xlsx(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); path = ExportService(db).export_excel_report(task.id, task_uuid); return FileResponse(path=path, filename=Path(path).name)


@router.get("/tasks/{task_uuid}/export/report.pdf")
def export_report_pdf(task_uuid: str, db: Session = Depends(get_db)):
    query = QueryService(db); task = query.get_task_or_raise(task_uuid); path = ExportService(db).export_pdf_report(task.id, task_uuid); return FileResponse(path=path, filename=Path(path).name)


@router.delete("/tasks/{task_uuid}")
def delete_task(task_uuid: str, db: Session = Depends(get_db)):
    repo = TaskRepository(db)
    ok = repo.delete_task_by_uuid(task_uuid)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "task_uuid": task_uuid}
