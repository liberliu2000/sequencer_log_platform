from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import orjson
from sqlalchemy.orm import Session

from app.core.logging_config import logger
from app.core.settings import get_settings
from app.correlators.pairing import pair_start_end
from app.db.session import SessionLocal
from app.detectors.error_detection import annotate_errors, top_error_clusters
from app.models.db_models import ErrorClusterModel, NormalizedEventModel, StepSummaryModel
from app.normalizers.event_normalizer import normalize_record
from app.parsers.registry import ParserRegistry
from app.repositories.task_repository import TaskRepository
from app.services.cycle_service import aggregate_metric_steps
from app.utils.files import ArchiveHandlingError, iter_supported_files, unpack_archive


class IngestionService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.repo = TaskRepository(db)
        self.registry = ParserRegistry()

    def save_batch_upload(self, files: list[tuple[str, bytes]]) -> str:
        task_uuid = uuid.uuid4().hex
        batch_dir = Path(self.settings.upload_dir) / task_uuid
        batch_dir.mkdir(parents=True, exist_ok=True)
        display_name = files[0][0] if len(files) == 1 else f"batch_{len(files)}files"
        task = self.repo.create_task(task_uuid=task_uuid, filename=display_name, stored_path=str(batch_dir))
        self.repo.update_task_progress(task.id, status="queued", current_stage="等待进入异步队列", file_count=len(files), message="批量上传完成")
        for name, content in files:
            stored_path = batch_dir / name
            stored_path.parent.mkdir(parents=True, exist_ok=True)
            stored_path.write_bytes(content)
        return task_uuid

    @staticmethod
    def process_task_by_uuid(task_uuid: str) -> None:
        db = SessionLocal()
        try:
            service = IngestionService(db)
            task = service.repo.get_task_by_uuid(task_uuid)
            if task:
                service.process_task(task.id, Path(task.stored_path))
        finally:
            db.close()

    def _progress(self, task_id: int, stage: str, percent: int, message: str | None = None, file_count: int | None = None) -> None:
        self.repo.update_task_progress(task_id, status="processing", current_stage=stage, progress_percent=percent, message=message, file_count=file_count, queue_position=None)

    def process_task(self, task_id: int, stored_root: Path) -> None:
        self._progress(task_id, "准备处理中", 1, message="开始创建本地工作区")
        work_dir = Path(self.settings.upload_dir) / f"work_{task_id}"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            collected_files: list[Path] = []
            upload_inputs = [p for p in stored_root.rglob("*") if p.is_file()] if stored_root.is_dir() else [stored_root]
            input_total = max(len(upload_inputs), 1)
            for idx, src in enumerate(upload_inputs, start=1):
                base_percent = 2 + int((idx - 1) / input_total * 20)
                self._progress(task_id, f"预处理输入 {idx}/{input_total}", base_percent, message=f"正在检查/解压: {src.name}")
                extracted = unpack_archive(
                    src,
                    work_dir / f"part_{idx}",
                    progress_callback=lambda stage, p, base=base_percent: self._progress(task_id, stage, min(25, base + int(p * 0.2))),
                )
                collected_files.extend(extracted)
            files = iter_supported_files(collected_files)
            self._progress(task_id, "文件识别完成", 28, message=f"识别到 {len(files)} 个可解析文件", file_count=len(files))

            all_events = []
            total_files = max(len(files), 1)
            for idx, file_path in enumerate(files, start=1):
                parser_name, generator = self.registry.parse_file(file_path)
                self._progress(task_id, f"解析文件 {idx}/{total_files}", 28 + int(idx / total_files * 42), message=f"{file_path.name} [{parser_name}]")
                logger.info("parsing_file", file=file_path.name, parser=parser_name)
                for record in generator:
                    all_events.append(normalize_record(record))

            self._progress(task_id, "错误归一化与聚类", 74, message=f"已生成 {len(all_events)} 条标准事件，开始错误去噪")
            all_events = annotate_errors(all_events)
            event_models = []
            for e in all_events:
                payload = e.model_dump()
                payload["extra_json"] = orjson.dumps(payload.get("extra_json") or {}).decode("utf-8")
                event_models.append(NormalizedEventModel(**payload))
            self.repo.save_events(task_id, event_models)

            self._progress(task_id, "步骤配对与成像聚合", 82, message="开始生成 workflow step 与 imaging metric 汇总")
            paired_steps = pair_start_end(all_events)
            metric_steps = aggregate_metric_steps(all_events)
            all_steps = paired_steps + metric_steps
            step_models = [StepSummaryModel(**s.model_dump()) for s in all_steps]
            if step_models:
                self.repo.save_step_summaries(task_id, step_models)

            self._progress(task_id, "生成错误簇统计", 90, message="开始汇总 Top 错误簇与频次")
            clusters = []
            cluster_rows = top_error_clusters(all_events, limit=200)
            for row in cluster_rows:
                matching = [e for e in all_events if e.normalized_signature == row["normalized_signature"]]
                first_seen = min((e.epoch_ms for e in matching if e.epoch_ms is not None), default=None)
                last_seen = max((e.epoch_ms for e in matching if e.epoch_ms is not None), default=None)
                clusters.append(
                    ErrorClusterModel(
                        normalized_signature=row["normalized_signature"],
                        error_family=row["error_family"],
                        severity=row["severity"],
                        representative_message=row["display_signature"],
                        representative_exception=row["exception_type"],
                        component=row["component"],
                        count=row["count"],
                        first_seen_epoch_ms=first_seen,
                        last_seen_epoch_ms=last_seen,
                    )
                )
            if clusters:
                self.repo.replace_error_clusters(task_id, clusters)

            total_errors = sum(1 for e in all_events if e.normalized_signature)
            self.repo.finalize_task(task_id, file_count=len(files), total_events=len(all_events), total_errors=total_errors)
        except ArchiveHandlingError as exc:
            logger.exception("archive_processing_failed", task_id=task_id, error=str(exc))
            self.repo.update_task_progress(task_id, status="failed", progress_percent=100, current_stage="解压失败", message=str(exc))
        except Exception as exc:
            logger.exception("task_processing_failed", task_id=task_id, error=str(exc))
            self.repo.update_task_progress(task_id, status="failed", progress_percent=100, current_stage="处理失败", message=str(exc))
