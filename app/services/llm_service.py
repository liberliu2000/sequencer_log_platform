from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.llm.client import LLMClient
from app.llm.prompts import build_error_analysis_prompt
from app.models.db_models import LLMAnalysisResultModel
from app.repositories.task_repository import TaskRepository
from app.services.prompt_template_service import PromptTemplateService
from app.services.query_service import QueryService


class LLMService:
    def __init__(self, db: Session):
        self.db = db
        self.client = LLMClient()
        self.query = QueryService(db)
        self.repo = TaskRepository(db)
        self.prompt_templates = PromptTemplateService()

    def analyze_signature(self, task_id: int, signature: str, force: bool = False) -> dict:
        if not force:
            existing = self.repo.get_latest_llm_result(task_id, signature)
            if existing:
                req = self._safe_json(existing.request_payload)
                resp = self._safe_json(existing.response_payload)
                return {
                    "structured_result": resp.get("structured_result", resp),
                    "chinese_summary": existing.chinese_summary,
                    "request_payload": req,
                    "response_payload": resp,
                    "context_summary": req.get("context_summary", {}),
                    "analysis_stage": existing.analysis_stage or req.get("analysis_stage", "light"),
                    "prompt_version": existing.prompt_version,
                    "from_cache": True,
                    "created_at": existing.created_at.isoformat(),
                }

        active_tpl = self.prompt_templates.get_active()
        cluster, context_rows, stats = self.query.get_context_for_signature(task_id, signature, stage="light")
        prompt = build_error_analysis_prompt(cluster, context_rows, stats, mode="light", template=active_tpl.get("template"))
        result, request_payload, response_payload = self.client.analyze(prompt)
        final_stage = "light"
        final_context_rows = context_rows
        final_stats = stats

        if self._should_deepen(result.model_dump(), stats):
            cluster2, context_rows2, stats2 = self.query.get_context_for_signature(task_id, signature, stage="deep")
            prompt2 = build_error_analysis_prompt(cluster2, context_rows2, stats2, mode="deep", template=active_tpl.get("template"))
            result, request_payload, response_payload = self.client.analyze(prompt2)
            final_stage = "deep"
            final_context_rows = context_rows2
            final_stats = stats2
            cluster = cluster2

        structured = result.model_dump()
        chinese_summary = self._build_cn_summary(structured)
        persisted_request = {
            "analysis_stage": final_stage,
            "prompt_version": active_tpl.get("active_version"),
            "cluster": cluster,
            "context_summary": final_stats.get("context_summary", {}),
            "stats": final_stats,
            "compressed_context_preview": final_context_rows,
            "llm_request": request_payload,
        }
        persisted_response = {"structured_result": structured, "llm_raw_response": response_payload}
        self.repo.save_llm_result(
            LLMAnalysisResultModel(
                task_id=task_id,
                normalized_signature=signature,
                model_name=self.client.settings.llm_model,
                prompt_version=active_tpl.get("active_version"),
                analysis_stage=final_stage,
                request_payload=json.dumps(persisted_request, ensure_ascii=False),
                response_payload=json.dumps(persisted_response, ensure_ascii=False),
                chinese_summary=chinese_summary,
            )
        )
        return {
            "structured_result": structured,
            "chinese_summary": chinese_summary,
            "request_payload": persisted_request,
            "response_payload": persisted_response,
            "context_summary": final_stats.get("context_summary", {}),
            "analysis_stage": final_stage,
            "prompt_version": active_tpl.get("active_version"),
            "from_cache": False,
        }

    def list_results(self, task_id: int) -> list[dict]:
        rows = self.repo.list_llm_results(task_id)
        out = []
        for r in rows:
            req = self._safe_json(r.request_payload)
            resp = self._safe_json(r.response_payload)
            out.append(
                {
                    "normalized_signature": r.normalized_signature,
                    "model_name": r.model_name,
                    "chinese_summary": r.chinese_summary,
                    "created_at": r.created_at.isoformat(),
                    "analysis_stage": r.analysis_stage or req.get("analysis_stage", "light"),
                    "prompt_version": r.prompt_version,
                    "context_summary": req.get("context_summary", {}),
                    "request_payload": req,
                    "response_payload": resp,
                }
            )
        return out

    @staticmethod
    def _safe_json(text: str):
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}

    @staticmethod
    def _should_deepen(data: dict, stats: dict) -> bool:
        confidence = float(data.get("confidence", 0.0) or 0.0)
        severe = str(data.get("severity", "")).lower() in {"high", "critical", "fatal"}
        compressed = int(stats.get("context_summary", {}).get("compressed_line_count", 0))
        return confidence < 0.55 or severe or compressed < 4

    def _build_cn_summary(self, data: dict) -> str:
        return (
            f"根因摘要：{data.get('root_cause_summary', '')}\n"
            f"可能原因：{'; '.join(data.get('possible_causes', []))}\n"
            f"影响模块：{'; '.join(data.get('affected_modules', []))}\n"
            f"建议检查：{'; '.join(data.get('recommended_checks', []))}\n"
            f"责任部门：{'; '.join(data.get('owner_departments', []))}\n"
            f"严重级别：{data.get('severity', '')}，置信度：{data.get('confidence', 0.0)}"
        )
