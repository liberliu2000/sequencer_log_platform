from __future__ import annotations

import re
from collections import defaultdict
import mimetypes
from pathlib import Path
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db_models import ErrorClusterModel, LLMAnalysisResultModel, NormalizedEventModel, StepSummaryModel, UploadTaskModel
from app.schemas.common import StepSummary
from app.services.cycle_service import summarize_cycles
from app.utils.timeparse import format_seconds
from app.llm.context import ContextConfig, compress_records
from app.core.settings import get_settings
from app.utils.rules import load_yaml


SEC_RE = re.compile(r"([0-9.]+)\s*sec", re.IGNORECASE)
ELAPSED_SEC_RE = re.compile(r"elapsed time[:=]\s*([0-9.]+)", re.IGNORECASE)
MS_RE = re.compile(r"Done in\s*([0-9.]+)ms", re.IGNORECASE)
TEMP_SET_RE = re.compile(r"SetSlideTemperature:\s*Slide\s*([NF])\s*setting temperature to\s*([0-9.]+)", re.IGNORECASE)
TEMP_DONE_RE = re.compile(r"SetSlideTemperature:\s*Slide\s*([NF])\s*successfully set temperature to\s*([0-9.]+)", re.IGNORECASE)
ROW_SCAN_RE = re.compile(r"Row scan Done in\s*([0-9.]+)ms", re.IGNORECASE)
PRIMING_RE = re.compile(r"cPAS reagent priming completed.*?cycle=\s*(\d+).*?span time:\s*([0-9.]+)s", re.IGNORECASE)
TRANSFER_RE = re.compile(r"Move slide from\s+(.+?)\s+finished", re.IGNORECASE)


class QueryService:
    def __init__(self, db: Session):
        self.db = db

    def get_task_or_raise(self, task_uuid: str) -> UploadTaskModel:
        stmt = select(UploadTaskModel).where(UploadTaskModel.task_uuid == task_uuid)
        task = self.db.scalar(stmt)
        if not task:
            raise ValueError("任务不存在")
        return task

    def list_events(
        self,
        task_id: int,
        component: str | None = None,
        level: str | None = None,
        cycle_no: int | None = None,
        chip_name: str | None = None,
        search: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        stmt = select(NormalizedEventModel).where(NormalizedEventModel.task_id == task_id)
        if component:
            stmt = stmt.where(NormalizedEventModel.component == component)
        if level:
            stmt = stmt.where(NormalizedEventModel.level == level.upper())
        if cycle_no is not None:
            stmt = stmt.where(NormalizedEventModel.cycle_no == cycle_no)
        if chip_name:
            stmt = stmt.where(NormalizedEventModel.chip_name == chip_name)
        if search:
            stmt = stmt.where(NormalizedEventModel.message.contains(search))
        stmt = stmt.order_by(NormalizedEventModel.epoch_ms.asc()).limit(limit)
        rows = list(self.db.scalars(stmt))
        return [
            {
                "id": r.id,
                "time": r.formatted_ms,
                "time_sec": format_seconds(r.parsed_datetime),
                "level": r.level,
                "component": r.component,
                "cycle_no": r.cycle_no,
                "sub_step": r.sub_step,
                "chip_name": r.chip_name,
                "method_name": r.method_name,
                "exception_type": r.exception_type,
                "error_code": r.error_code,
                "message": r.message,
                "source_file": r.source_file,
            }
            for r in rows
        ]

    def list_cycles(self, task_id: int) -> list[int]:
        rows = self.db.execute(
            select(NormalizedEventModel.cycle_no)
            .where(NormalizedEventModel.task_id == task_id, NormalizedEventModel.cycle_no.is_not(None))
            .distinct()
            .order_by(NormalizedEventModel.cycle_no.asc())
        )
        return [int(r[0]) for r in rows if r[0] is not None]

    def get_dashboard(self, task_id: int) -> dict[str, Any]:
        file_count = self.db.scalar(
            select(func.count(func.distinct(NormalizedEventModel.source_file))).where(NormalizedEventModel.task_id == task_id)
        ) or 0
        total_events = self.db.scalar(
            select(func.count()).select_from(NormalizedEventModel).where(NormalizedEventModel.task_id == task_id)
        ) or 0
        total_errors = self.db.scalar(
            select(func.count()).select_from(NormalizedEventModel).where(
                NormalizedEventModel.task_id == task_id,
                NormalizedEventModel.normalized_signature.is_not(None),
            )
        ) or 0
        unique_error_count = self.db.scalar(
            select(func.count(func.distinct(NormalizedEventModel.normalized_signature))).where(
                NormalizedEventModel.task_id == task_id,
                NormalizedEventModel.normalized_signature.is_not(None),
            )
        ) or 0
        top_errors = list(
            self.db.execute(
                select(
                    ErrorClusterModel.normalized_signature,
                    ErrorClusterModel.error_family,
                    ErrorClusterModel.count,
                    ErrorClusterModel.component,
                    ErrorClusterModel.representative_message,
                )
                .where(ErrorClusterModel.task_id == task_id)
                .order_by(ErrorClusterModel.count.desc(), ErrorClusterModel.last_seen_epoch_ms.desc())
                .limit(10)
            )
        )
        components = list(
            self.db.execute(
                select(NormalizedEventModel.component, func.count())
                .where(
                    NormalizedEventModel.task_id == task_id,
                    NormalizedEventModel.normalized_signature.is_not(None),
                )
                .group_by(NormalizedEventModel.component)
                .order_by(func.count().desc())
            )
        )
        return {
            "file_count": file_count,
            "total_events": total_events,
            "total_errors": total_errors,
            "unique_error_count": unique_error_count,
            "top_errors": [
                {
                    "normalized_signature": r[0],
                    "display_signature": r[4],
                    "error_family": r[1],
                    "count": r[2],
                    "component": r[3],
                    "message": r[4],
                }
                for r in top_errors
            ],
            "component_distribution": [{"component": c or "未知", "count": n} for c, n in components],
        }

    def get_step_summaries(self, task_id: int, cycle_no: int | None = None) -> list[dict]:
        stmt = select(StepSummaryModel).where(StepSummaryModel.task_id == task_id)
        if cycle_no is not None:
            stmt = stmt.where(StepSummaryModel.cycle_no == cycle_no)
        stmt = stmt.order_by(
            StepSummaryModel.cycle_no.asc(), StepSummaryModel.start_epoch_ms.asc(), StepSummaryModel.sub_step.asc()
        )
        rows = list(self.db.scalars(stmt))
        return [
            {
                "cycle_no": r.cycle_no,
                "sub_step": r.sub_step,
                "component": r.component,
                "chip_name": r.chip_name,
                "start_epoch_ms": r.start_epoch_ms,
                "end_epoch_ms": r.end_epoch_ms,
                "duration_ms": r.duration_ms,
                "threshold_ms": r.threshold_ms,
                "is_over_threshold": r.is_over_threshold,
                "start_time_text": r.start_time_text,
                "end_time_text": r.end_time_text,
                "start_time_sec": self._epoch_to_seconds(r.start_epoch_ms),
                "end_time_sec": self._epoch_to_seconds(r.end_epoch_ms),
            }
            for r in rows
        ]

    def get_cycle_summaries(self, task_id: int, unit: str = "ms") -> list[dict]:
        rows = self.get_step_summaries(task_id)
        summaries = summarize_cycles([self._dict_to_step(row) for row in rows])
        output = []
        for s in summaries:
            item = s.model_dump(mode="json")
            item["started_at_text"] = self._epoch_to_seconds(item.get("started_at"))
            item["ended_at_text"] = self._epoch_to_seconds(item.get("ended_at"))
            item["total_duration_value"] = self._convert_duration(item.get("total_duration_ms"), unit)
            item["duration_unit"] = unit
            output.append(item)
        return output

    def get_error_clusters(self, task_id: int) -> list[dict]:
        stmt = select(ErrorClusterModel).where(ErrorClusterModel.task_id == task_id).order_by(ErrorClusterModel.count.desc())
        rows = list(self.db.scalars(stmt))
        return [
            {
                "normalized_signature": r.normalized_signature,
                "display_signature": r.representative_message,
                "error_family": r.error_family,
                "severity": r.severity,
                "component": r.component,
                "count": r.count,
                "representative_message": r.representative_message,
                "representative_exception": r.representative_exception,
                "first_seen_epoch_ms": r.first_seen_epoch_ms,
                "last_seen_epoch_ms": r.last_seen_epoch_ms,
                "first_seen_text": self._epoch_to_seconds(r.first_seen_epoch_ms),
                "last_seen_text": self._epoch_to_seconds(r.last_seen_epoch_ms),
            }
            for r in rows
        ]

    def get_context_for_signature(self, task_id: int, signature: str, stage: str = "light") -> tuple[dict, list[dict], dict]:
        settings = get_settings()
        llm_cfg = load_yaml(settings.thresholds_path).get("llm_context", {})
        cfg = ContextConfig(
            pre_lines=int(llm_cfg.get("pre_lines", settings.llm_context_pre_lines)),
            post_lines=int(llm_cfg.get("post_lines", settings.llm_context_post_lines)),
            time_window_seconds=int(llm_cfg.get("time_window_seconds", settings.llm_context_time_window_seconds)),
            related_component_limit=int(llm_cfg.get("related_component_limit", settings.llm_context_related_component_limit)),
            related_cycle_limit=int(llm_cfg.get("related_cycle_limit", settings.llm_context_related_cycle_limit)),
            max_stack_frames=int(llm_cfg.get("max_stack_frames", settings.llm_context_max_stack_frames)),
            max_token_budget=int(llm_cfg.get("max_token_budget", settings.llm_context_max_token_budget)),
            stage1_token_budget=int(llm_cfg.get("stage1_token_budget", settings.llm_context_stage1_token_budget)),
        )
        cluster_stmt = select(ErrorClusterModel).where(
            ErrorClusterModel.task_id == task_id,
            ErrorClusterModel.normalized_signature == signature,
        )
        cluster = self.db.scalar(cluster_stmt)
        if not cluster:
            raise ValueError("错误簇不存在")

        anchor_stmt = (
            select(NormalizedEventModel)
            .where(
                NormalizedEventModel.task_id == task_id,
                NormalizedEventModel.normalized_signature == signature,
            )
            .order_by(NormalizedEventModel.epoch_ms.asc())
            .limit(1)
        )
        anchor = self.db.scalar(anchor_stmt)
        context_rows: list[dict[str, Any]] = []
        raw_rows: list[dict[str, Any]] = []
        if anchor and anchor.epoch_ms is not None:
            budget = cfg.stage1_token_budget if stage == "light" else cfg.max_token_budget
            win_ms = cfg.time_window_seconds * 1000
            stmt = (
                select(NormalizedEventModel)
                .where(
                    NormalizedEventModel.task_id == task_id,
                    NormalizedEventModel.epoch_ms >= anchor.epoch_ms - win_ms,
                    NormalizedEventModel.epoch_ms <= anchor.epoch_ms + win_ms,
                )
                .order_by(NormalizedEventModel.epoch_ms.asc(), NormalizedEventModel.id.asc())
            )
            related_component = 0
            related_cycle = 0
            anchor_component = anchor.component
            anchor_cycle = anchor.cycle_no
            anchor_method = anchor.method_name
            for idx, r in enumerate(self.db.scalars(stmt)):
                item = {
                    "time": r.formatted_ms,
                    "time_sec": format_seconds(r.parsed_datetime),
                    "level": r.level,
                    "component": r.component,
                    "module": r.module,
                    "cycle_no": r.cycle_no,
                    "sub_step": r.sub_step,
                    "chip_name": r.chip_name,
                    "method_name": r.method_name,
                    "exception_type": r.exception_type,
                    "error_code": r.error_code,
                    "source_path": r.source_path,
                    "line_no": r.line_no,
                    "message": r.message,
                }
                is_anchor = r.normalized_signature == signature
                same_component = bool(anchor_component and r.component == anchor_component)
                same_cycle = anchor_cycle is not None and r.cycle_no == anchor_cycle
                same_method = bool(anchor_method and r.method_name == anchor_method)
                is_important = (r.level or "").upper() in {"WARN", "ERROR", "FATAL"} or is_anchor
                is_state_change = bool(r.sub_step) or any(tok in (r.message or "").lower() for tok in ["start", "completed", "done", "timeout", "exception", "failed"])
                if is_anchor or is_important:
                    raw_rows.append(item)
                    continue
                if same_method and is_state_change:
                    raw_rows.append(item)
                    continue
                if same_component and (is_state_change or (r.level or "").upper() == "WARN") and related_component < cfg.related_component_limit:
                    related_component += 1
                    raw_rows.append(item)
                    continue
                if same_cycle and (is_state_change or (r.level or "").upper() in {"WARN", "ERROR"}) and related_cycle < cfg.related_cycle_limit:
                    related_cycle += 1
                    raw_rows.append(item)
                    continue
                if idx >= 0 and len(raw_rows) < cfg.pre_lines + cfg.post_lines:
                    raw_rows.append(item)
            context_rows, compression_stats = compress_records(raw_rows, cfg, budget)
        else:
            compression_stats = {"raw_line_count": 0, "compressed_line_count": 0, "raw_estimated_tokens": 0, "compressed_estimated_tokens": 0, "compression_ratio": 1.0, "token_compression_ratio": 1.0, "token_budget": cfg.stage1_token_budget if stage == "light" else cfg.max_token_budget}
        dashboard = self.get_dashboard(task_id)
        stats = {
            "task_summary": {
                "total_events": dashboard.get("total_events", 0),
                "total_errors": dashboard.get("total_errors", 0),
                "unique_error_count": dashboard.get("unique_error_count", 0),
            },
            "context_summary": {
                **compression_stats,
                "analysis_stage": stage,
                "anchor_component": anchor.component if anchor else None,
                "anchor_cycle": anchor.cycle_no if anchor else None,
                "anchor_sub_step": anchor.sub_step if anchor else None,
            },
        }
        cluster_dict = {
            "normalized_signature": cluster.normalized_signature,
            "display_signature": cluster.representative_message,
            "error_family": cluster.error_family,
            "severity": cluster.severity,
            "component": cluster.component,
            "count": cluster.count,
            "representative_message": cluster.representative_message,
            "representative_exception": cluster.representative_exception,
            "error_summary": {
                "time": anchor.formatted_ms if anchor else None,
                "time_sec": format_seconds(anchor.parsed_datetime) if anchor and anchor.parsed_datetime else None,
                "component": anchor.component if anchor else cluster.component,
                "module": anchor.module if anchor else None,
                "function": anchor.method_name if anchor else None,
                "error_type": anchor.exception_type if anchor else cluster.representative_exception,
                "error_code": anchor.error_code if anchor else None,
                "cycle": anchor.cycle_no if anchor else None,
                "sub_step": anchor.sub_step if anchor else None,
                "chip_name": anchor.chip_name if anchor else None,
            },
        }
        return cluster_dict, context_rows, stats

    def get_movement_timeline(self, task_id: int, cycle_no: int | None = None) -> list[dict[str, Any]]:
        rows = self.get_step_summaries(task_id, cycle_no=cycle_no)
        output = []
        for r in rows:
            sub_step = str(r.get("sub_step") or "")
            component = str(r.get("component") or "")
            if not (r.get("start_epoch_ms") and r.get("end_epoch_ms")):
                continue
            movement_like = any(
                key in sub_step.lower()
                for key in ["move", "align", "scan", "transfer", "temperature", "priming", "coarsetheta", "finealign"]
            ) or component in {"XYZStage", "Scanner_1", "Scanner_2", "Workflow", "StageRunMgr", "ImagingMetrics"}
            if not movement_like:
                continue
            output.append(
                {
                    **r,
                    "start": datetime.fromtimestamp(r["start_epoch_ms"] / 1000).isoformat(),
                    "end": datetime.fromtimestamp(r["end_epoch_ms"] / 1000).isoformat(),
                    "track": f"{r.get('component') or '未知部件'} | Cycle {r.get('cycle_no') or 'NA'}",
                }
            )
        return output

    def get_operational_metrics(self, task_id: int, cycle_no: int | None = None) -> dict[str, Any]:
        events = self._get_events(task_id, cycle_no=cycle_no)
        photo_rows: list[dict[str, Any]] = []
        transfer_rows: list[dict[str, Any]] = []
        priming_rows: list[dict[str, Any]] = []
        temp_rows: list[dict[str, Any]] = []
        metric_stage_rows: list[dict[str, Any]] = []
        temp_open: dict[tuple[str, float], dict] = {}

        for ev in events:
            msg = ev.message or ""
            cycle = ev.cycle_no
            chip = ev.chip_name
            ts = ev.formatted_ms or format_seconds(ev.parsed_datetime)

            m = ELAPSED_SEC_RE.search(msg)
            if "MoveStageFromLoadPosToFirstField elapsed time" in msg and m:
                photo_rows.append(self._metric_row(cycle, chip, "MoveStageFromLoadPosToFirstField", float(m.group(1)) * 1000.0, ts, ev.component))

            m = SEC_RE.search(msg)
            if "CoarseThetaWithoutMoveStage Completed in" in msg and m:
                photo_rows.append(self._metric_row(cycle, chip, "CoarseThetaWithoutMoveStage", float(m.group(1)) * 1000.0, ts, ev.component))
            elif "FineAlign Completed in" in msg and m:
                photo_rows.append(self._metric_row(cycle, chip, "FineAlign", float(m.group(1)) * 1000.0, ts, ev.component))

            m = ROW_SCAN_RE.search(msg)
            if m:
                photo_rows.append(self._metric_row(cycle, chip, "Row scan", float(m.group(1)), ts, ev.component))

            m = PRIMING_RE.search(msg)
            if m:
                prim_cycle = int(m.group(1))
                priming_rows.append(self._metric_row(prim_cycle, chip, "cPAS reagent priming", float(m.group(2)) * 1000.0, ts, ev.component))

            if "Move slide from" in msg and "finished" in msg:
                transfer_name = TRANSFER_RE.search(msg)
                duration = ev.duration_ms
                if duration is None:
                    duration = self._scan_numeric_ms(msg)
                transfer_rows.append(self._metric_row(cycle, chip, transfer_name.group(0) if transfer_name else "机械臂转移", duration, ts, ev.component, msg))

            m = TEMP_SET_RE.search(msg)
            if m:
                slide, target = m.group(1).upper(), float(m.group(2))
                temp_open[(slide, target)] = {
                    "start_epoch_ms": ev.epoch_ms,
                    "cycle_no": cycle,
                    "chip_name": chip,
                    "time": ts,
                    "component": ev.component,
                }
            m = TEMP_DONE_RE.search(msg)
            if m:
                slide, target = m.group(1).upper(), float(m.group(2))
                start = temp_open.pop((slide, target), None)
                if start and start.get("start_epoch_ms") and ev.epoch_ms:
                    temp_rows.append(
                        {
                            "cycle_no": cycle,
                            "chip_name": chip,
                            "slide": slide,
                            "target_temperature": target,
                            "temperature_phase": self._temp_phase(slide, target),
                            "duration_ms": float(ev.epoch_ms - start["start_epoch_ms"]),
                            "time": ts,
                            "component": ev.component,
                        }
                    )

            if ev.component == "ImagingMetrics" and ev.sub_step and ev.duration_ms is not None:
                metric_stage_rows.append(
                    {
                        "cycle_no": cycle,
                        "chip_name": chip,
                        "metric_stage": str(ev.sub_step).replace("imaging::", ""),
                        "duration_ms": float(ev.duration_ms),
                        "time": ts,
                    }
                )

        metric_avg_rows = self._aggregate_metric_stage_rows(metric_stage_rows)
        photo_summary = self._aggregate_named_metrics(photo_rows)
        transfer_summary = self._aggregate_named_metrics(transfer_rows)
        priming_summary = self._aggregate_named_metrics(priming_rows)

        return {
            "photo_times": photo_rows,
            "photo_summary": photo_summary,
            "transfer_times": transfer_rows,
            "transfer_summary": transfer_summary,
            "cpas_priming_times": priming_rows,
            "cpas_priming_summary": priming_summary,
            "temperature_times": temp_rows,
            "metric_stage_avg": metric_avg_rows,
        }

    @staticmethod
    def _metric_row(cycle_no, chip_name, metric_name, duration_ms, time_text, component, raw_message: str | None = None):
        return {
            "cycle_no": cycle_no,
            "chip_name": chip_name,
            "metric_name": metric_name,
            "duration_ms": float(duration_ms) if duration_ms is not None else None,
            "time": time_text,
            "component": component,
            "raw_message": raw_message,
        }

    def _aggregate_metric_stage_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[int | None, str | None, str], list[float]] = defaultdict(list)
        for row in rows:
            grouped[(row["cycle_no"], row["chip_name"], row["metric_stage"])].append(row["duration_ms"])
        result = []
        for (cycle_no, chip_name, metric_stage), values in sorted(grouped.items(), key=lambda x: ((x[0][0] or -1), x[0][2])):
            result.append(
                {
                    "cycle_no": cycle_no,
                    "chip_name": chip_name,
                    "metric_stage": metric_stage,
                    "row_count": len(values),
                    "avg_duration_ms": round(sum(values) / len(values), 3),
                }
            )
        return result

    def _aggregate_named_metrics(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[int | None, str | None, str], list[float]] = defaultdict(list)
        latest_time: dict[tuple[int | None, str | None, str], str | None] = {}
        for row in rows:
            if row.get("duration_ms") is None:
                continue
            key = (row.get("cycle_no"), row.get("chip_name"), row.get("metric_name"))
            grouped[key].append(float(row["duration_ms"]))
            latest_time[key] = row.get("time")
        result = []
        for (cycle_no, chip_name, metric_name), values in sorted(grouped.items(), key=lambda x: ((x[0][0] or -1), x[0][2])):
            result.append(
                {
                    "cycle_no": cycle_no,
                    "chip_name": chip_name,
                    "metric_name": metric_name,
                    "count": len(values),
                    "avg_duration_ms": round(sum(values) / len(values), 3),
                    "max_duration_ms": round(max(values), 3),
                    "min_duration_ms": round(min(values), 3),
                    "time": latest_time.get((cycle_no, chip_name, metric_name)),
                }
            )
        return result

    def _get_events(self, task_id: int, cycle_no: int | None = None) -> list[NormalizedEventModel]:
        stmt = select(NormalizedEventModel).where(NormalizedEventModel.task_id == task_id)
        if cycle_no is not None:
            stmt = stmt.where(NormalizedEventModel.cycle_no == cycle_no)
        stmt = stmt.order_by(NormalizedEventModel.epoch_ms.asc())
        return list(self.db.scalars(stmt))

    @staticmethod
    def _scan_numeric_ms(msg: str) -> float | None:
        for pattern, scale in [(re.compile(r"span time[:=]\s*([0-9.]+)s", re.IGNORECASE), 1000.0), (re.compile(r"Done in\s*([0-9.]+)ms", re.IGNORECASE), 1.0)]:
            m = pattern.search(msg)
            if m:
                return float(m.group(1)) * scale
        return None

    @staticmethod
    def _temp_phase(slide: str, target: float) -> str:
        phase = "升温" if target >= 30 else "降温"
        return f"{phase}时间 {slide}"

    @staticmethod
    def _convert_duration(duration_ms: float | None, unit: str) -> float | None:
        if duration_ms is None:
            return None
        unit = (unit or "ms").lower()
        factor = {"ms": 1, "s": 1000, "sec": 1000, "m": 60000, "min": 60000, "h": 3600000, "hour": 3600000}.get(unit, 1)
        return round(float(duration_ms) / factor, 3)

    @staticmethod
    def _dict_to_step(row: dict):
        return StepSummary(**row)

    @staticmethod
    def _epoch_to_seconds(epoch_ms: int | None) -> str | None:
        if epoch_ms is None:
            return None
        dt = datetime.fromtimestamp(epoch_ms / 1000)
        return format_seconds(dt)

    def get_audit_logs(self, task_id: int, limit: int = 200) -> list[dict]:
        from app.models.db_models import TaskAuditLogModel
        stmt = select(TaskAuditLogModel).where(TaskAuditLogModel.task_id == task_id).order_by(TaskAuditLogModel.created_at.desc()).limit(limit)
        rows = list(self.db.scalars(stmt))
        return [{"action": r.action, "status": r.status, "stage": r.stage, "detail": r.detail, "actor": r.actor, "created_at": r.created_at.isoformat()} for r in rows]

    def get_llm_results(self, task_id: int, limit: int = 200) -> list[dict]:
        stmt = select(LLMAnalysisResultModel).where(LLMAnalysisResultModel.task_id == task_id).order_by(LLMAnalysisResultModel.created_at.desc()).limit(limit)
        rows = list(self.db.scalars(stmt))
        out = []
        for r in rows:
            request_payload = r.request_payload
            response_payload = r.response_payload
            try:
                request_payload = json.loads(request_payload) if isinstance(request_payload, str) and request_payload else request_payload
            except Exception:
                pass
            try:
                response_payload = json.loads(response_payload) if isinstance(response_payload, str) and response_payload else response_payload
            except Exception:
                pass
            out.append({
                "normalized_signature": r.normalized_signature,
                "model_name": r.model_name,
                "prompt_version": r.prompt_version,
                "analysis_stage": r.analysis_stage,
                "request_payload": request_payload,
                "response_payload": response_payload,
                "chinese_summary": r.chinese_summary,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
        return out

    def list_task_files(self, task_id: int) -> list[dict]:
        task = self.db.scalar(select(UploadTaskModel).where(UploadTaskModel.id == task_id))
        if not task:
            return []
        path = Path(task.stored_path)
        if not path.exists():
            return []
        rows = []
        for p in sorted(path.rglob("*")):
            if p.is_file():
                mime_type, _ = mimetypes.guess_type(str(p))
                rows.append({
                    "relative_path": p.relative_to(path).as_posix(),
                    "size": p.stat().st_size,
                    "mime_type": mime_type or "application/octet-stream",
                    "suffix": p.suffix.lower(),
                })
        return rows

    def preview_task_file(self, task_id: int, relative_path: str, max_lines: int = 200) -> dict:
        task = self.db.scalar(select(UploadTaskModel).where(UploadTaskModel.id == task_id))
        if not task:
            raise ValueError("任务不存在")
        path = (Path(task.stored_path) / relative_path).resolve()
        root = Path(task.stored_path).resolve()
        if root not in path.parents and path != root:
            raise ValueError("非法文件路径")
        if not path.exists() or not path.is_file():
            raise ValueError("文件不存在")

        raw = path.read_bytes()
        sample = raw[: min(len(raw), 65536)]
        mime_type, _ = mimetypes.guess_type(str(path))
        binary_like = b"\x00" in sample
        if not binary_like:
            non_printable = sum(1 for b in sample if b < 9 or (13 < b < 32))
            binary_like = len(sample) > 0 and non_printable / max(len(sample), 1) > 0.10

        if binary_like:
            preview_lines = [sample[:256].hex()]
            return {
                "relative_path": relative_path,
                "line_count": 1,
                "preview": preview_lines,
                "encoding": None,
                "mime_type": mime_type or "application/octet-stream",
                "is_binary": True,
                "note": "该文件疑似二进制，预览已切换为十六进制摘要。",
            }

        detected_encoding = "utf-8"
        try:
            import chardet
            detected = chardet.detect(sample)
            if detected and detected.get("encoding"):
                detected_encoding = detected["encoding"]
        except Exception:
            pass

        text_data = raw.decode(detected_encoding, errors="replace")
        lines = []
        for i, line in enumerate(text_data.splitlines()):
            if i >= max_lines:
                break
            lines.append(line)
        return {
            "relative_path": relative_path,
            "line_count": len(lines),
            "preview": lines,
            "encoding": detected_encoding,
            "mime_type": mime_type or "text/plain",
            "is_binary": False,
            "note": None,
        }

    def get_error_regression_trend(self, task_id: int, signature: str | None = None, family: str | None = None, bucket: str = 'day') -> list[dict]:
        bucket = 'week' if bucket == 'week' else 'day'
        stmt = select(UploadTaskModel.id, UploadTaskModel.created_at).where(UploadTaskModel.status == 'completed')
        tasks = list(self.db.execute(stmt))
        result = []
        for tid, created_at in tasks:
            q = select(func.count()).select_from(NormalizedEventModel).where(NormalizedEventModel.task_id == tid, NormalizedEventModel.normalized_signature.is_not(None))
            if signature:
                q = q.where(NormalizedEventModel.normalized_signature == signature)
            if family:
                q = q.where(NormalizedEventModel.error_family == family)
            count = self.db.scalar(q) or 0
            if count <= 0:
                continue
            dt = created_at.date()
            bucket_key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}" if bucket == 'week' else dt.isoformat()
            result.append((bucket_key, count))
        agg = defaultdict(int)
        for k, c in result:
            agg[k] += c
        return [{"bucket": k, "count": agg[k]} for k in sorted(agg.keys())]
