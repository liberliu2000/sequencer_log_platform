from __future__ import annotations

from collections import defaultdict

from app.schemas.common import CycleSummary, NormalizedEvent, StepSummary
from app.utils.timeparse import parse_datetime, to_epoch_ms


IMAGING_METRIC_STEP_ORDER = [
    "imaging::setup",
    "imaging::move2start",
    "imaging::setTDIdir",
    "imaging::caculateImageType",
    "imaging::setupPEG",
    "imaging::waitForBCSRearyTime",
    "imaging::completeAcq",
    "imaging::sendrowInfo",
    "imaging::endmove2start",
    "imaging::waitForAFTime",
    "imaging::enablePEG",
    "imaging::turnLaserOnTime",
    "imaging::scan",
    "imaging::turnLaserOffTime",
    "imaging::ScanTotalTime",
]


def summarize_cycles(step_summaries: list[StepSummary]) -> list[CycleSummary]:
    by_cycle = defaultdict(list)
    for item in step_summaries:
        by_cycle[(item.cycle_no, item.chip_name)].append(item)

    result = []
    for (cycle_no, chip_name), items in by_cycle.items():
        starts = [i.start_epoch_ms for i in items if i.start_epoch_ms is not None]
        ends = [i.end_epoch_ms for i in items if i.end_epoch_ms is not None]
        direct_durations = [i.duration_ms for i in items if i.duration_ms is not None and i.start_epoch_ms is None and i.end_epoch_ms is None]
        total_ms = None
        if starts and ends:
            total_ms = max(ends) - min(starts)
        elif direct_durations:
            total_ms = float(sum(direct_durations))
        result.append(
            CycleSummary(
                cycle_no=cycle_no,
                chip_name=chip_name,
                total_duration_ms=total_ms,
                started_at=min(starts) if starts else None,
                ended_at=max(ends) if ends else None,
            )
        )
    return sorted(result, key=lambda x: (x.cycle_no or -1, x.chip_name or ""))


def aggregate_metric_steps(events: list[NormalizedEvent]) -> list[StepSummary]:
    summaries: list[StepSummary] = []

    imaging_groups: dict[tuple[int | None, str | None, str], list[NormalizedEvent]] = defaultdict(list)
    fov_groups: dict[tuple[int | None, str | None], list[NormalizedEvent]] = defaultdict(list)

    for event in events:
        if event.parser_name != "metrics_csv":
            continue
        if event.component == "ImagingMetrics" and event.sub_step:
            imaging_groups[(event.cycle_no, event.chip_name, event.sub_step)].append(event)
        elif event.component == "FOVMetrics":
            fov_groups[(event.cycle_no, event.chip_name)].append(event)

    for (cycle_no, chip_name, sub_step), rows in imaging_groups.items():
        durations = [float(e.duration_ms) for e in rows if e.duration_ms is not None]
        if not durations:
            continue
        summaries.append(
            StepSummary(
                cycle_no=cycle_no,
                sub_step=sub_step,
                component="ImagingMetrics",
                chip_name=chip_name,
                duration_ms=sum(durations),
                threshold_ms=None,
                is_over_threshold=False,
            )
        )

    for (cycle_no, chip_name), rows in fov_groups.items():
        timestamps = []
        for row in rows:
            dt_text = row.extra_json.get("DateTime") if isinstance(row.extra_json, dict) else None
            dt = parse_datetime(dt_text) if dt_text else row.parsed_datetime
            epoch = to_epoch_ms(dt) if dt else row.epoch_ms
            if epoch is not None:
                timestamps.append(epoch)
        if len(timestamps) >= 2:
            summaries.append(
                StepSummary(
                    cycle_no=cycle_no,
                    sub_step="fov_capture_window",
                    component="FOVMetrics",
                    chip_name=chip_name,
                    start_epoch_ms=min(timestamps),
                    end_epoch_ms=max(timestamps),
                    duration_ms=float(max(timestamps) - min(timestamps)),
                    threshold_ms=None,
                    is_over_threshold=False,
                )
            )

    return sorted(
        summaries,
        key=lambda s: (
            s.cycle_no or -1,
            0 if s.sub_step in IMAGING_METRIC_STEP_ORDER else 1,
            IMAGING_METRIC_STEP_ORDER.index(s.sub_step) if s.sub_step in IMAGING_METRIC_STEP_ORDER else 999,
            s.sub_step,
            s.chip_name or "",
        ),
    )
