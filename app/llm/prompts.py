from __future__ import annotations

import json


def build_error_analysis_prompt(error_cluster: dict, context_events: list[dict], stats: dict, mode: str = "light", template: dict | None = None) -> str:
    template = template or {}
    policy = template.get("analysis_policy") or "优先根据错误摘要、关键 warning/error、状态变化与精简堆栈判断。"
    analysis_hint = (
        "先做轻量诊断，若证据不足请明确说明不确定点。"
        if mode == "light"
        else "这是深入诊断阶段。可结合跨文件同 cycle/同组件上下文继续分析，但仍只根据已提供内容判断。"
    )
    return f"""
你是一名测序仪控制系统问题诊断专家。请根据下面的错误簇、最小必要上下文和统计信息进行诊断，仅返回 JSON。

返回字段:
{{
  "root_cause_summary": "",
  "possible_causes": [],
  "affected_modules": [],
  "recommended_checks": [],
  "owner_departments": [],
  "severity": "",
  "confidence": 0.0
}}

owner_departments 仅允许以下候选:
["软件控制","流路系统","光学系统","运动平台","调度系统","数据算法","硬件电气","测试运维"]

规则:
- 严禁臆断未提供的外部事实
- 优先保留与当前错误直接相关的步骤状态变化、warning/error、必要堆栈
- 忽略无关成功日志与重复堆栈
- {policy}
- {analysis_hint}

错误簇:
{json.dumps(error_cluster, ensure_ascii=False, indent=2)}

最小必要上下文:
{json.dumps(context_events, ensure_ascii=False, indent=2)}

统计信息:
{json.dumps(stats, ensure_ascii=False, indent=2)}
""".strip()
