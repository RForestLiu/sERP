"""
Collect 域 - 采集引擎（包装 collector.py）。

将原有的 collector.py 采集流水线包装为领域基础设施，
通过 SettingsFacade 获取 AI 模型配置，保持与原有 collector.py 的兼容。
"""
import os
import logging

logger = logging.getLogger(__name__)


class CollectionEngine:
    """采集引擎 — 包装 collector.py 的爬取、分类、下载流水线"""

    def __init__(self, settings_facade, data_root: str):
        self._settings_facade = settings_facade
        self._data_root = data_root

        # 注入环境变量供 collector.py 使用
        self._ensure_env_from_settings()

    def _ensure_env_from_settings(self):
        """从 SettingsFacade 读取 AI 模型配置并同步到环境变量"""
        try:
            model_id = self._settings_facade.get_feature_model("product_collect_image_classify")
            if model_id:
                models = self._settings_facade.get_models()
                for m in models:
                    if m.get("id") == model_id:
                        api_key_env = m.get("api_key_env", "")
                        base_url = m.get("base_url", "")
                        # collector.py 从环境变量读取配置
                        if api_key_env:
                            key_value = os.getenv(api_key_env, "")
                            if key_value:
                                os.environ["DEEPSEEK_API_KEY"] = key_value
                        if base_url:
                            os.environ.setdefault("DEEPSEEK_API_URL", base_url)
                        break
        except Exception as e:
            logger.warning("Failed to resolve collection model config: %s", e)

    async def run_pipeline(self, url: str, task_id: str, status_callback=None) -> dict:
        """执行完整采集流水线（与 collector.py run_collect_pipeline 接口兼容）"""
        # 动态导入 collector.py，注入 data_root
        try:
            import collector
        except ImportError:
            collector = None

        # 临时覆盖 DATA_ROOT 以使用新的目录结构
        import collector as collector_mod

        original_data_root = collector_mod.DATA_ROOT
        collector_mod.DATA_ROOT = self._data_root

        try:
            result = await collector_mod.run_collect_pipeline(url, task_id, status_callback)
            return result
        finally:
            collector_mod.DATA_ROOT = original_data_root
