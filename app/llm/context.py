from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ContextConfig:
    pre_lines: int = 8
    post_lines: int = 8
    time_window_seconds: int = 90
    related_component_limit: int = 30
    related_cycle_limit: int = 30
    max_stack_frames: int = 8
    max_token_budget: int = 2200
    stage1_token_budget: int = 1200


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 3.5))


def _normalize_line(item: dict[str, Any]) -> str:
    text = f"{item.get('level','')}|{item.get('component','')}|{item.get('method_name','')}|{item.get('exception_type','')}|{item.get('message','')}"
    text = re.sub(r"\b\d+\b", "#", text)
    text = re.sub(r"0x[a-fA-F0-9]+", "0x#", text)
    text = re.sub(r"[A-Z]:\\[^ ]+", "PATH", text)
    return text


def _compress_stack(message: str, max_frames: int) -> str:
    lines = [l for l in str(message).splitlines() if l.strip()]
    if len(lines) <= max_frames + 1:
        return "\n".join(lines)
    return "\n".join(lines[:1] + lines[1:max_frames+1])


def compress_records(raw_rows: list[dict[str, Any]], cfg: ContextConfig, token_budget: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen = set()
    for row in raw_rows:
        row = dict(row)
        row["message"] = _compress_stack(str(row.get("message") or ""), cfg.max_stack_frames)
        key = _normalize_line(row)
        if key in seen:
            continue
        if str(row.get("level", "")).upper() == "INFO" and not row.get("sub_step") and "completed" in str(row.get("message", "")).lower():
            continue
        seen.add(key)
        deduped.append(row)

    raw_text = "\n".join(str(r) for r in raw_rows)
    compressed = list(deduped)
    while compressed and estimate_tokens("\n".join(str(r) for r in compressed)) > token_budget:
        next_rows: list[dict[str, Any]] = []
        for r in compressed:
            level = str(r.get("level", "")).upper()
            msg = str(r.get("message", "")).lower()
            if level in {"ERROR", "FATAL", "WARN"} or r.get("sub_step") or r.get("exception_type") or "timeout" in msg or "exception" in msg or "failed" in msg:
                next_rows.append(r)
        if len(next_rows) == len(compressed):
            compressed = compressed[: max(5, len(compressed) - 5)]
        else:
            compressed = next_rows

    compressed_text = "\n".join(str(r) for r in compressed)
    raw_tokens = estimate_tokens(raw_text)
    compressed_tokens = estimate_tokens(compressed_text)
    stats = {
        "raw_line_count": len(raw_rows),
        "compressed_line_count": len(compressed),
        "raw_estimated_tokens": raw_tokens,
        "compressed_estimated_tokens": compressed_tokens,
        "compression_ratio": round(len(compressed) / max(1, len(raw_rows)), 4),
        "token_compression_ratio": round(compressed_tokens / max(1, raw_tokens), 4),
        "token_budget": token_budget,
    }
    return compressed, stats
