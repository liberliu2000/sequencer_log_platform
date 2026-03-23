from __future__ import annotations

from pathlib import Path
from typing import Type

from app.parsers.base import BaseParser
from app.parsers.csv_workflow_parser import CsvWorkflowParser
from app.parsers.error_log_parser import ErrorLogParser
from app.parsers.metrics_csv_parser import MetricsCsvParser
from app.parsers.runerror_parser import RunErrorParser
from app.parsers.service_log_parser import ServiceLogParser


class ParserRegistry:
    def __init__(self):
        self.parsers: list[Type[BaseParser]] = [
            MetricsCsvParser,
            CsvWorkflowParser,
            ServiceLogParser,
            ErrorLogParser,
            RunErrorParser,
        ]

    def choose(self, path: Path) -> BaseParser:
        head_text = ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                head_text = f.read(4096)
        except Exception:
            head_text = path.name
        scored = [(parser_cls.score(path, head_text), parser_cls) for parser_cls in self.parsers]
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_cls = scored[0]
        return best_cls()

    def parse_file(self, path: Path):
        parser = self.choose(path)
        return parser.name, parser.parse(path)
