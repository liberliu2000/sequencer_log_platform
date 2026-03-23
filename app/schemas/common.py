from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RawLogRecord(BaseModel):
    source_file: str
    parser_name: str
    raw_text: str
    original_time_text: str | None = None
    level: str | None = None
    component: str | None = None
    module: str | None = None
    thread: str | None = None
    method_name: str | None = None
    class_name: str | None = None
    source_path: str | None = None
    line_no: int | None = None
    message: str
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedEvent(BaseModel):
    source_file: str
    parser_name: str
    original_time_text: str | None = None
    parsed_datetime: datetime | None = None
    epoch_ms: int | None = None
    formatted_ms: str | None = None
    level: str = "INFO"
    component: str | None = None
    module: str | None = None
    thread: str | None = None
    method_name: str | None = None
    class_name: str | None = None
    source_path: str | None = None
    line_no: int | None = None
    message: str
    raw_text: str
    cycle_no: int | None = None
    sub_step: str | None = None
    chip_name: str | None = None
    stage_name: str | None = None
    board_name: str | None = None
    event_kind: str | None = None
    direction: str | None = None
    duration_ms: float | None = None
    status: str | None = None
    error_code: str | None = None
    exception_type: str | None = None
    normalized_signature: str | None = None
    error_family: str | None = None
    severity: str | None = None
    extra_json: dict[str, Any] = Field(default_factory=dict)


class CycleSummary(BaseModel):
    cycle_no: int | None = None
    chip_name: str | None = None
    total_duration_ms: float | None = None
    started_at: int | None = None
    ended_at: int | None = None


class StepSummary(BaseModel):
    cycle_no: int | None = None
    sub_step: str
    component: str | None = None
    chip_name: str | None = None
    start_epoch_ms: int | None = None
    end_epoch_ms: int | None = None
    duration_ms: float | None = None
    threshold_ms: float | None = None
    is_over_threshold: bool = False
    start_time_text: str | None = None
    end_time_text: str | None = None


class ErrorSignature(BaseModel):
    normalized_signature: str
    error_family: str | None = None
    error_severity: str | None = None
    representative_message: str
    exception_type: str | None = None
    function_name: str | None = None


class ErrorOccurrence(BaseModel):
    normalized_signature: str
    event_id: int | None = None
    cycle_no: int | None = None
    component: str | None = None
    epoch_ms: int | None = None
    message: str


class LLMAnalysisResult(BaseModel):
    root_cause_summary: str = ""
    possible_causes: list[str] = Field(default_factory=list)
    affected_modules: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    owner_departments: list[str] = Field(default_factory=list)
    severity: str = "unknown"
    confidence: float = 0.0


class UploadTaskResponse(BaseModel):
    task_uuid: str
    filename: str
    status: str
    file_count: int
    total_events: int
    total_errors: int
    message: str | None = None


class DashboardSummary(BaseModel):
    file_count: int
    total_events: int
    total_errors: int
    unique_error_count: int
    top_errors: list[dict[str, Any]]
    component_distribution: list[dict[str, Any]]
