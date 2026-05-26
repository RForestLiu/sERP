import copy
import json
import logging
import os
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests

from src.serp.settings.domain.services import PRODUCT_CLEAN_DEFAULT_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatCompletionEndpoint:
    base_url: str

    def request_url(self, tools: list[dict]) -> str:
        base_url = str(self.base_url or "").rstrip("/")
        has_strict_tool = any((t.get("function") or {}).get("strict") is True for t in tools)
        if has_strict_tool and base_url == "https://api.deepseek.com/v1/chat/completions":
            return "https://api.deepseek.com/beta/chat/completions"
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return base_url


class ProductDataCleaner:
    def __init__(self, settings_facade):
        self._settings = settings_facade

    def clean(self, raw_data: dict) -> dict:
        raw_copy = copy.deepcopy(raw_data) if isinstance(raw_data, dict) else {}
        config = self._resolve_config()
        language = self._resolve_language()
        prompt = self._resolve_prompt()
        audit = {
            "model": config.get("model", ""),
            "language": language,
            "cleaned_at": datetime.now().isoformat(),
            "status": "failed",
            "evidence": {},
            "review": {},
        }

        try:
            cleaned = self._call_clean_llm(config, language, raw_copy, prompt)
            params, evidence = self._normalize_params(cleaned.get("product_param", {}))
            description = self._normalize_description(cleaned.get("product_description", {}))
            audit["evidence"] = evidence
            audit["review"] = {
                "passed": True,
                "skipped": True,
                "reason": "temporarily_disabled_for_model_output_review",
                "issues": [],
                "checks": [],
            }
            audit["status"] = "ok"
            return {
                "product_data": {
                    "product_param": params,
                    "product_description": description,
                },
                "raw_product_data": raw_copy,
                "clean_audit": audit,
            }
        except Exception as exc:
            logger.warning("[collect] product data clean failed: %s", exc)
            audit["error"] = str(exc)
            return {
                "product_data": self._fallback_product_data(raw_copy),
                "raw_product_data": raw_copy,
                "clean_audit": audit,
            }

    def availability(self) -> tuple[bool, str, dict]:
        config = self._resolve_config()
        if not config.get("api_key"):
            return False, f"{config.get('api_key_env') or 'API key'} not configured", config
        return True, "", config

    def _resolve_config(self) -> dict:
        config = {
            "base_url": os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"),
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": os.getenv("DEEPSEEK_PRODUCT_CLEAN_MODEL", "deepseek-v4-pro"),
        }
        try:
            model_id = self._settings.get_feature_model("product_data_clean")
            models = {m.get("id"): m for m in self._settings.get_models() if isinstance(m, dict)}
            selected = models.get(model_id)
            if selected:
                config["base_url"] = selected.get("base_url") or config["base_url"]
                config["model"] = selected.get("model") or config["model"]
                api_key_env = selected.get("api_key_env") or "DEEPSEEK_API_KEY"
                config["api_key_env"] = api_key_env
                config["api_key"] = os.getenv(api_key_env, config["api_key"])
        except Exception as exc:
            logger.warning("[collect] settings model resolve failed: %s", exc)
        return config

    def _resolve_language(self) -> str:
        try:
            view = self._settings.get_view()
            value = getattr(view, "product_clean_language", "")
            if not value:
                value = getattr(view, "settings", {}).get("product_clean_language", "")
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass
        return "English"

    def _resolve_prompt(self) -> str:
        try:
            view = self._settings.get_view()
            value = getattr(view, "product_clean_prompt", "")
            if not value:
                value = getattr(view, "settings", {}).get("product_clean_prompt", "")
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass
        return PRODUCT_CLEAN_DEFAULT_PROMPT

    def _call_clean_llm(
        self,
        config: dict,
        language: str,
        raw_data: dict,
        system_prompt: str,
        retry_reason: dict | None = None,
    ) -> dict:
        user_prompt = json.dumps({
            "output_language": language,
            "return_schema": {
                "product_param": [
                    {"key": "snake_case_field_name", "value": "field value with unit", "evidence": "source field or exact text"}
                ],
                "product_description": {"summary": "cleaned description", "evidence": ["source field or exact text"]},
            },
            "raw_product_data": raw_data,
        }, ensure_ascii=False)
        if retry_reason:
            user_prompt = json.dumps({
                "previous_attempt_failed": retry_reason,
                "output_language": language,
                "raw_product_data": raw_data,
                "return_schema": {
                    "product_param": [
                        {"key": "snake_case_field_name", "value": f"translated {language} value with unit", "evidence": "source field or exact text"}
                    ],
                    "product_description": {"summary": f"translated {language} description", "evidence": ["source field or exact text"]},
                },
            }, ensure_ascii=False)
        return self._call_llm(
            config,
            system_prompt,
            user_prompt,
            1200,
            tool=self._clean_tool_schema(),
            tool_name="clean_product_data",
        )

    def _call_review_llm(self, config: dict, language: str, raw_data: dict,
                         params: dict, description: str, evidence: dict) -> dict:
        system_prompt = (
            "You are a product data auditor. Output JSON only. "
            "Verify product_param contains only objective facts with evidence. "
            "Verify product_description does not contain objective size/weight/spec parameters. "
            "Reject hallucinated fields not supported by raw_product_data."
        )
        user_prompt = json.dumps({
            "output_language": language,
            "raw_product_data": raw_data,
            "product_data": {"product_param": params, "product_description": description},
            "evidence": evidence,
            "return_schema": {
                "passed": True,
                "issues": [],
                "checks": [{"field": "", "result": "pass/fail", "evidence": ""}],
            },
        }, ensure_ascii=False)
        return self._call_llm(
            config,
            system_prompt,
            user_prompt,
            800,
            tool=self._audit_tool_schema(),
            tool_name="audit_product_data",
        )

    def _call_llm(
        self,
        config: dict,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        tool: Optional[dict] = None,
        tool_name: str = "",
    ) -> dict:
        if not config.get("api_key"):
            raise ValueError(f"{config.get('api_key_env') or 'API key'} not configured")
        payload = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        tools = [tool] if tool else []
        if tool:
            payload["tools"] = tools
            payload["tool_choice"] = {"type": "function", "function": {"name": tool_name}}
            if "v4-pro" in str(config["model"]).lower():
                payload["thinking"] = {"type": "disabled"}
        else:
            payload["response_format"] = {"type": "json_object"}
            if "v4-pro" in str(config["model"]).lower():
                payload["enable_thinking"] = False
        resp = requests.post(
            ChatCompletionEndpoint(config["base_url"]).request_url(tools),
            headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LLM request failed: HTTP {resp.status_code}: {resp.text[:300]}")
        message = resp.json().get("choices", [{}])[0].get("message", {})
        arguments = self._tool_arguments(message)
        if arguments:
            return json.loads(arguments)
        content = str(message.get("content", "") or "").strip()
        if not content:
            raise ValueError("LLM returned empty structured output")
        return json.loads(content)

    @staticmethod
    def _tool_arguments(message: dict) -> str:
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return ""
        function = tool_calls[0].get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            return arguments.strip()
        if isinstance(arguments, dict):
            return json.dumps(arguments, ensure_ascii=False)
        return ""

    @staticmethod
    def _clean_tool_schema() -> dict:
        return {
            "type": "function",
            "function": {
                "name": "clean_product_data",
                "description": "Return cleaned ecommerce product data with evidence.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "product_param": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                    "evidence": {"type": "string"},
                                },
                                "required": ["key", "value", "evidence"],
                            },
                        },
                        "product_description": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "summary": {"type": "string"},
                                "evidence": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["summary", "evidence"],
                        },
                    },
                    "required": ["product_param", "product_description"],
                },
            },
        }

    @staticmethod
    def _audit_tool_schema() -> dict:
        return {
            "type": "function",
            "function": {
                "name": "audit_product_data",
                "description": "Audit cleaned product data against raw source evidence.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "passed": {"type": "boolean"},
                        "issues": {"type": "array", "items": {"type": "string"}},
                        "checks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "field": {"type": "string"},
                                    "result": {"type": "string", "enum": ["pass", "fail"]},
                                    "evidence": {"type": "string"},
                                },
                                "required": ["field", "result", "evidence"],
                            },
                        },
                    },
                    "required": ["passed", "issues", "checks"],
                },
            },
        }

    @staticmethod
    def _normalize_params(raw_params) -> tuple[dict, dict]:
        params = {}
        evidence = {}
        if isinstance(raw_params, list):
            items = ((item.get("key", ""), item) for item in raw_params if isinstance(item, dict))
        elif isinstance(raw_params, dict):
            items = raw_params.items()
        else:
            return params, evidence
        for key, item in items:
            name = str(key).strip()
            if not name:
                continue
            if isinstance(item, dict):
                value = item.get("value", "")
                ev = item.get("evidence", "")
            else:
                value = item
                ev = ""
            if value in (None, "", [], {}):
                continue
            params[name] = str(value).strip()
            evidence[name] = ev
        return params, evidence

    @staticmethod
    def _normalize_description(raw_description) -> str:
        if isinstance(raw_description, dict):
            return str(raw_description.get("summary", "")).strip()
        return str(raw_description or "").strip()

    @staticmethod
    def _review_output_language(language: str, params: dict, description: str) -> dict:
        if not str(language or "").lower().startswith("english"):
            return {}
        checks = []
        for key, value in params.items():
            if ProductDataCleaner._contains_non_latin_letters(str(value)):
                checks.append({
                    "field": f"product_param.{key}",
                    "result": "fail",
                    "evidence": str(value)[:120],
                })
        if ProductDataCleaner._contains_non_latin_letters(description):
            checks.append({
                "field": "product_description",
                "result": "fail",
                "evidence": description[:120],
            })
        if not checks:
            return {}
        checks.append({
            "field": "output_language",
            "result": "fail",
            "evidence": "Cleaned product data must be English, but non-Latin letters remain.",
        })
        return {
            "passed": False,
            "issues": ["language_mismatch"],
            "checks": checks,
        }

    @staticmethod
    def _merge_review_failure(review: dict, failure: dict) -> dict:
        merged = dict(review) if isinstance(review, dict) else {}
        issues = list(merged.get("issues") or [])
        for issue in failure.get("issues") or []:
            if issue not in issues:
                issues.append(issue)
        merged["passed"] = False
        merged["issues"] = issues
        merged["checks"] = list(merged.get("checks") or []) + list(failure.get("checks") or [])
        return merged

    @staticmethod
    def _contains_non_latin_letters(text: str) -> bool:
        for char in text or "":
            if not char.isalpha():
                continue
            if "LATIN" not in unicodedata.name(char, ""):
                return True
        return False

    @staticmethod
    def _fallback_product_data(raw_data: dict) -> dict:
        details = raw_data.get("product_details", {}) if isinstance(raw_data.get("product_details"), dict) else {}
        description_parts = [
            raw_data.get("about_item", ""),
            raw_data.get("product_description", ""),
            raw_data.get("description", ""),
        ]
        return {
            "product_param": {str(k): str(v) for k, v in details.items() if v not in (None, "", [], {})},
            "product_description": "\n".join(str(p).strip() for p in description_parts if str(p).strip()),
        }
