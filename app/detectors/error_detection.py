from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from app.schemas.common import NormalizedEvent
from app.utils.text import build_error_display_label, remove_dynamic_tokens, sha1_short


ERROR_FAMILY_RULES = [
    ("timeout", [r"timeout", r"time out"]),
    ("connection_lost", [r"connectionlostexception", r"connection lost", r"broken pipe"]),
    ("rpc_ice", [r"\bice\.", r"\brpc\b"]),
    ("db_open_failure", [r"db open", r"database", r"sqlite"]),
    ("bad_image_format", [r"bad image format", r"image format"]),
    ("file_io", [r"file not found", r"ioexception", r"cannot open file"]),
    ("movement_stage_failure", [r"stage", r"movement", r"axis", r"homing"]),
    ("optics_camera_failure", [r"camera", r"optic", r"exposure", r"focus"]),
]

NOISE_PATTERNS = [
    r"create logger",
    r"logger:",
    r"debug trace",
]


def normalize_error_signature(event: NormalizedEvent) -> tuple[str | None, str | None, str | None]:
    message = event.message or ""
    lowered = message.lower()
    if event.level not in {"WARN", "ERROR", "FATAL"} and not any(
        k in lowered for k in ["exception", "error", "timeout", "failed"]
    ):
        return None, None, None

    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in NOISE_PATTERNS):
        return None, None, None

    family = classify_error_family(" ".join(filter(None, [event.exception_type, event.method_name, message])))
    severity = "fatal" if event.level == "FATAL" else "error" if event.level == "ERROR" else "warning"
    display_label = build_error_display_label(event.exception_type, event.method_name, message, max_len=160)

    signature_core = " | ".join(
        p
        for p in [
            family,
            event.component,
            event.exception_type,
            event.method_name,
            remove_dynamic_tokens(message.lower())[:180],
        ]
        if p
    )
    signature = sha1_short(signature_core or message)
    event.extra_json = dict(event.extra_json or {})
    event.extra_json["display_signature"] = display_label
    event.extra_json["signature_core"] = signature_core[:240]
    return signature, family, severity


def classify_error_family(text: str) -> str:
    t = text.lower()
    for family, patterns in ERROR_FAMILY_RULES:
        if any(re.search(p, t, re.IGNORECASE) for p in patterns):
            return family
    return "general_error"


def annotate_errors(events: Iterable[NormalizedEvent]) -> list[NormalizedEvent]:
    result = []
    for event in events:
        signature, family, severity = normalize_error_signature(event)
        event.normalized_signature = signature
        event.error_family = family
        event.severity = severity
        result.append(event)
    return result


def top_error_clusters(events: list[NormalizedEvent], limit: int = 20) -> list[dict]:
    counter = Counter(e.normalized_signature for e in events if e.normalized_signature)
    representatives = {}
    for e in events:
        if e.normalized_signature and e.normalized_signature not in representatives:
            representatives[e.normalized_signature] = e
    rows = []
    for signature, count in counter.most_common(limit):
        rep = representatives[signature]
        display_label = None
        if isinstance(rep.extra_json, dict):
            display_label = rep.extra_json.get("display_signature")
        rows.append(
            {
                "normalized_signature": signature,
                "display_signature": display_label or rep.message[:120],
                "count": count,
                "error_family": rep.error_family,
                "severity": rep.severity,
                "component": rep.component,
                "message": rep.message,
                "exception_type": rep.exception_type,
            }
        )
    return rows
