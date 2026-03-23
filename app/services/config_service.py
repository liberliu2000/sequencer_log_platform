from __future__ import annotations

from app.core.settings import get_settings
from app.utils.rules import load_yaml, save_yaml
from app.services.prompt_template_service import PromptTemplateService


class ConfigService:
    def __init__(self):
        self.settings = get_settings()

    def get_all(self) -> dict:
        return {
            "thresholds": load_yaml(self.settings.thresholds_path),
            "parser_rules": load_yaml(self.settings.parser_rules_path),
            "error_rules": load_yaml(self.settings.error_rules_path),
            "prompt_templates": PromptTemplateService().get_templates(),
            "llm": {
                "enabled": self.settings.llm_enabled,
                "base_url": self.settings.llm_base_url,
                "model": self.settings.llm_model,
                "timeout_seconds": self.settings.llm_timeout_seconds,
                "max_retries": self.settings.llm_max_retries,
                "context": {
                    "pre_lines": self.settings.llm_context_pre_lines,
                    "post_lines": self.settings.llm_context_post_lines,
                    "time_window_seconds": self.settings.llm_context_time_window_seconds,
                    "related_component_limit": self.settings.llm_context_related_component_limit,
                    "related_cycle_limit": self.settings.llm_context_related_cycle_limit,
                    "max_stack_frames": self.settings.llm_context_max_stack_frames,
                    "max_token_budget": self.settings.llm_context_max_token_budget,
                    "stage1_token_budget": self.settings.llm_context_stage1_token_budget,
                },
            },
        }

    def update_thresholds(self, data: dict) -> dict:
        save_yaml(self.settings.thresholds_path, data)
        return data
