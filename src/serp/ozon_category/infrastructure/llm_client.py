"""
OzonCategory 域 - DeepSeek LLM HTTP 客户端。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import requests

from ..domain.value_objects import LLMConfig

logger = logging.getLogger(__name__)


class DeepSeekLLMClient:
    """DeepSeek LLM 客户端 — 封装 HTTP 调用（翻译 + 分类匹配）"""

    def __init__(self, config: LLMConfig):
        self._base_url = config.base_url
        self._api_key = config.api_key
        self._model = config.model

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def model(self) -> str:
        return self._model

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 32768,
        json_format: bool = False,
    ) -> tuple[Optional[dict], str]:
        """
        调用 DeepSeek LLM。
        返回: (response_dict, error_message)
        成功: ({"choices": [...], ...}, "")
        失败: (None, error_string)
        """
        if not self._api_key:
            return None, "DeepSeek API key 未配置"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_format:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(
                self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300 if max_tokens > 4096 else 120,
            )
            if resp.status_code != 200:
                logger.warning("[DeepSeek] HTTP %s: %s", resp.status_code, resp.text[:300])
                return None, f"DeepSeek API Error {resp.status_code}: {resp.text[:300]}"

            return resp.json(), ""
        except Exception as e:
            logger.error("[DeepSeek] 调用异常: %s", e)
            return None, str(e)

    def translate(self, prompt: str, batch_label: str = "翻译") -> tuple[dict[str, str], int, int]:
        """
        便捷翻译方法。返回 (translations, translated_count, error_count)
        """
        system = "你是俄语→中文电商翻译专家。只返回 JSON，不要其他内容。"
        result, err = self.call(system, prompt, temperature=0.1, max_tokens=32768)
        if err or not result:
            return {}, 0, 0

        import re
        import json as _json
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned)
        try:
            parsed = _json.loads(cleaned)
        except _json.JSONDecodeError:
            logger.warning("[%s] JSON 解析失败", batch_label)
            return {}, 0, 0

        translations = {}
        for t in parsed.get("translations", []):
            tid = str(t.get("id"))
            name_cn = t.get("name_cn", "")
            if tid and name_cn:
                translations[tid] = name_cn

        tc = len(translations)
        logger.info("[%s] 翻译完成: %s 个", batch_label, tc)
        return translations, tc, 0

    @staticmethod
    def resolve_config(settings_facade, feature_key: str = "translation") -> LLMConfig:
        """从 SettingsFacade 解析 LLM 配置"""
        import os
        base_url = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        model = "deepseek-v4-pro"

        try:
            model_id = settings_facade.get_feature_model(feature_key)
            models = settings_facade.get_models()
            for m in models:
                if m.get("id") == model_id:
                    base_url = m.get("base_url") or base_url
                    model = m.get("model") or model
                    api_key_env = m.get("api_key_env") or "DEEPSEEK_API_KEY"
                    api_key = os.getenv(api_key_env, api_key)
                    break
        except Exception as e:
            logger.warning("LLM config resolve failed: %s", e)

        return LLMConfig(base_url=base_url, api_key=api_key, model=model)
