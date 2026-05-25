import copy
import json
import logging
import os
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class ProductDataCleaner:
    def __init__(self, settings_facade):
        self._settings = settings_facade

    def clean(self, raw_data: dict) -> dict:
        raw_copy = copy.deepcopy(raw_data) if isinstance(raw_data, dict) else {}
        config = self._resolve_config()
        language = self._resolve_language()
        audit = {
            "model": config.get("model", ""),
            "language": language,
            "cleaned_at": datetime.now().isoformat(),
            "status": "failed",
            "evidence": {},
            "review": {},
        }

        try:
            cleaned = self._call_clean_llm(config, language, raw_copy)
            params, evidence = self._normalize_params(cleaned.get("product_param", {}))
            description = self._normalize_description(cleaned.get("product_description", {}))
            audit["evidence"] = evidence
            review = self._call_review_llm(config, language, raw_copy, params, description, evidence)
            audit["review"] = review
            audit["status"] = "ok" if review.get("passed") is True else "review_failed"
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

    def _resolve_config(self) -> dict:
        config = {
            "base_url": os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"),
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
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

    def _call_clean_llm(self, config: dict, language: str, raw_data: dict) -> dict:
        system_prompt = (
            "You are an ecommerce product data cleaning assistant. Output JSON only. "
            "Return exactly two first-level fields: product_param and product_description. "
            "product_param must contain only objective facts as flat snake_case key-value pairs, "
            "for example product_length, product_width, product_height, product_weight, material, color. "
            "Each product_param item must include value and evidence. "
            "product_description is for subjective or marketing copy such as Amazon About this item "
            "or Wildberries Description."
        )
        user_prompt = json.dumps({
            "output_language": language,
            "return_schema": {
                "product_param": {
                    "snake_case_field_name": {"value": "field value with unit", "evidence": "source field or exact text"}
                },
                "product_description": {"summary": "cleaned description", "evidence": ["source field or exact text"]},
            },
            "raw_product_data": raw_data,
        }, ensure_ascii=False)
        return self._call_llm(config, system_prompt, user_prompt, 1200)

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
        return self._call_llm(config, system_prompt, user_prompt, 800)

    def _call_llm(self, config: dict, system_prompt: str, user_prompt: str, max_tokens: int) -> dict:
        if not config.get("api_key"):
            raise ValueError("DEEPSEEK_API_KEY not configured")
        payload = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if "v4-pro" in str(config["model"]).lower():
            payload["enable_thinking"] = False
        resp = requests.post(
            config["base_url"],
            headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"LLM request failed: HTTP {resp.status_code}: {resp.text[:300]}")
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return json.loads(content.strip())

    @staticmethod
    def _normalize_params(raw_params) -> tuple[dict, dict]:
        params = {}
        evidence = {}
        if not isinstance(raw_params, dict):
            return params, evidence
        for key, item in raw_params.items():
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
