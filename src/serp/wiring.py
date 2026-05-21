"""
wiring.py — 依赖注入装配。

集中创建所有域 Facade 实例、事件总线、仓储，供给 app.py。
目前只完整实现了 Settings 域，其他域后续追加。
"""
import os
import logging

from src.serp.shared import SyncEventBus, FacadeRegistry

logger = logging.getLogger(__name__)

STORES_FILE = None  # 由 init() 设置，供旧 app.py 路由兼容


def create_settings_facade(data_root: str, env_file: str):
    """装配 Settings 域：仓储 → 事件总线 → 应用服务 → 蓝图"""
    from src.serp.settings.domain.events import (
        SettingsUpdated,
        EnvVariablesChanged,
        StoreCreated,
        StoreUpdated,
        StoreRemoved,
        SettingsImported,
    )
    from src.serp.settings.infrastructure.json_repositories import (
        JsonSettingsRepository,
        JsonStoreRepository,
        DotEnvRepository,
    )
    from src.serp.settings.infrastructure import handlers
    from src.serp.settings.application.commands import SettingsApplicationService

    event_bus = SyncEventBus()

    # 事件订阅
    event_bus.subscribe(SettingsUpdated, handlers.log_settings_updated)
    event_bus.subscribe(EnvVariablesChanged, handlers.log_env_changed)
    event_bus.subscribe(StoreCreated, handlers.log_store_created)
    event_bus.subscribe(StoreUpdated, handlers.log_store_updated)
    event_bus.subscribe(StoreRemoved, handlers.log_store_removed)
    event_bus.subscribe(SettingsImported, handlers.log_settings_imported)

    settings_repo = JsonSettingsRepository(os.path.join(data_root, "settings.json"))
    store_repo = JsonStoreRepository(os.path.join(data_root, "stores.json"))
    env_repo = DotEnvRepository(env_file)

    facade = SettingsApplicationService(settings_repo, store_repo, env_repo, event_bus)

    global STORES_FILE
    STORES_FILE = os.path.join(data_root, "stores.json")

    logger.info("Settings domain wired: event_bus=%s, repos=3", event_bus.__class__.__name__)
    return facade, event_bus


def create_logistics_facade(data_root: str):
    """装配 Logistics 域"""
    from src.serp.logistics.infrastructure.json_repositories import JsonLogisticsTemplateRepository
    from src.serp.logistics.application.commands import LogisticsApplicationService

    templates_dir = os.path.join(data_root, "logistics_templates")
    repo = JsonLogisticsTemplateRepository(templates_dir)
    facade = LogisticsApplicationService(repo)

    logger.info("Logistics domain wired: repo=%s", repo.__class__.__name__)
    return facade


def create_ozon_category_facade(data_root: str, settings_facade, event_bus):
    """装配 OzonCategory 域：仓储 → API/LLM 客户端 → 应用服务"""
    from src.serp.ozon_category.domain.events import (
        CategoryTreeFetched,
        CategoriesTranslated,
        CategoriesRefreshed,
        CategoryMatchCompleted,
    )
    from src.serp.ozon_category.infrastructure.json_repositories import (
        JsonCategoryTreeCacheRepository,
        JsonTranslationCacheRepository,
        JsonAttributeTranslationCacheRepository,
        JsonExcludedCategoriesRepository,
    )
    from src.serp.ozon_category.infrastructure.ozon_api_client import OzonApiClient
    from src.serp.ozon_category.infrastructure.llm_client import DeepSeekLLMClient
    from src.serp.ozon_category.infrastructure import handlers
    from src.serp.ozon_category.application.commands import OzonCategoryApplicationService
    from src.serp.settings.infrastructure.json_repositories import JsonStoreRepository

    # 事件订阅
    event_bus.subscribe(CategoryTreeFetched, handlers.log_category_tree_fetched)
    event_bus.subscribe(CategoriesTranslated, handlers.log_categories_translated)
    event_bus.subscribe(CategoriesRefreshed, handlers.log_categories_refreshed)
    event_bus.subscribe(CategoryMatchCompleted, handlers.log_category_match_completed)

    # 缓存目录
    cache_dir = os.path.join(data_root, "ozon_cache")
    os.makedirs(cache_dir, exist_ok=True)

    # 仓储
    tree_cache_repo = JsonCategoryTreeCacheRepository(cache_dir)
    trans_cache_repo = JsonTranslationCacheRepository(cache_dir)
    attr_trans_cache_repo = JsonAttributeTranslationCacheRepository(cache_dir)
    excluded_repo = JsonExcludedCategoriesRepository(cache_dir)

    # Ozon API 凭证获取器（使用 StoreRepository 读取原始凭证）
    store_repo = JsonStoreRepository(os.path.join(data_root, "stores.json"))

    def _get_ozon_credentials(store_id: str) -> tuple[str, str]:
        """从 StoreRepository 获取原始凭证，解析 ${VAR} 占位符"""
        import re as _re
        store = store_repo.find_by_id(store_id)
        if store is None:
            return "", ""
        client_id = str(store.client_id or "")
        api_key = str(store.api_key or "")
        def _resolve_env(value: str) -> str:
            if not value:
                return ""
            def _replace(match):
                var_name = match.group(1)
                return os.environ.get(var_name, match.group(0))
            return _re.sub(r'\$\{([^}]+)\}', _replace, value)
        return _resolve_env(client_id), _resolve_env(api_key)

    # API 和 LLM 客户端
    ozon_api = OzonApiClient(_get_ozon_credentials)
    llm_config = DeepSeekLLMClient.resolve_config(settings_facade, "translation")
    llm_client = DeepSeekLLMClient(llm_config)

    # 应用服务
    facade = OzonCategoryApplicationService(
        tree_cache_repo=tree_cache_repo,
        trans_cache_repo=trans_cache_repo,
        attr_trans_cache_repo=attr_trans_cache_repo,
        excluded_repo=excluded_repo,
        ozon_api=ozon_api,
        llm_client=llm_client,
    )

    logger.info("OzonCategory domain wired: repos=4, ozon_api=%s, llm=%s",
                ozon_api.__class__.__name__, llm_client.model)
    return facade


def create_product_facade(data_root: str, settings_facade, event_bus):
    """装配 Product 域：仓储 → 事件总线 → 应用服务"""
    from src.serp.product.domain.events import (
        ProductDeleted,
        ProductManualUpdated,
        SpecsCollected,
        ProductAutoExtracted,
        StoreStatusChanged,
        ImageSetsUpdated,
        ProductImageUploaded,
        ProductVideoUploaded,
        ProductCriticalChangeProposed,
        ProductCriticalFieldApproved,
        ProductCriticalFieldRejected,
    )
    from src.serp.product.infrastructure.json_repositories import JsonProductRepository
    from src.serp.product.infrastructure import handlers
    from src.serp.product.application.commands import ProductApplicationService

    # 事件订阅
    event_bus.subscribe(ProductDeleted, handlers.log_product_deleted)
    event_bus.subscribe(ProductManualUpdated, handlers.log_product_manual_updated)
    event_bus.subscribe(SpecsCollected, handlers.log_specs_collected)
    event_bus.subscribe(ProductAutoExtracted, handlers.log_product_auto_extracted)
    event_bus.subscribe(StoreStatusChanged, handlers.log_store_status_changed)
    event_bus.subscribe(ImageSetsUpdated, handlers.log_image_sets_updated)
    event_bus.subscribe(ProductImageUploaded, handlers.log_product_image_uploaded)
    event_bus.subscribe(ProductVideoUploaded, handlers.log_product_video_uploaded)
    event_bus.subscribe(ProductCriticalChangeProposed, handlers.log_critical_change_proposed)
    event_bus.subscribe(ProductCriticalFieldApproved, handlers.log_critical_field_approved)
    event_bus.subscribe(ProductCriticalFieldRejected, handlers.log_critical_field_rejected)

    product_repo = JsonProductRepository(os.path.join(data_root, "products.json"))
    videos_dir = os.path.join(data_root, "videos")

    facade = ProductApplicationService(
        product_repo=product_repo,
        settings_facade=settings_facade,
        event_bus=event_bus,
        data_root=data_root,
        videos_dir=videos_dir,
    )

    logger.info("Product domain wired")
    return facade


def create_imagetask_facade(data_root: str, settings_facade, event_bus):
    """装配 ImageTask 域：仓储 → 事件总线 → 应用服务"""
    from src.serp.imagetask.domain.events import (
        TaskCreated,
        TaskDeleted,
        TaskUpdated,
        ImagesGenerated,
        ImagesSaved,
        ImagesCompressed,
        SourceImagesUploaded,
        ReferenceImageUploaded,
        ImagesImported,
        ImagesSavedToProduct,
        ImagesCopiedToClipboard,
        TaskFolderOpened,
    )
    from src.serp.imagetask.infrastructure.json_repositories import JsonImageTaskRepository
    from src.serp.imagetask.infrastructure import handlers
    from src.serp.imagetask.application.commands import ImageTaskApplicationService

    # 事件订阅
    event_bus.subscribe(TaskCreated, handlers.log_task_created)
    event_bus.subscribe(TaskDeleted, handlers.log_task_deleted)
    event_bus.subscribe(TaskUpdated, handlers.log_task_updated)
    event_bus.subscribe(ImagesGenerated, handlers.log_images_generated)
    event_bus.subscribe(ImagesSaved, handlers.log_images_saved)
    event_bus.subscribe(ImagesCompressed, handlers.log_images_compressed)
    event_bus.subscribe(SourceImagesUploaded, handlers.log_source_images_uploaded)
    event_bus.subscribe(ReferenceImageUploaded, handlers.log_reference_image_uploaded)
    event_bus.subscribe(ImagesImported, handlers.log_images_imported)
    event_bus.subscribe(ImagesSavedToProduct, handlers.log_images_saved_to_product)
    event_bus.subscribe(ImagesCopiedToClipboard, handlers.log_images_copied_to_clipboard)
    event_bus.subscribe(TaskFolderOpened, handlers.log_task_folder_opened)

    tasks_file = os.path.join(data_root, "tasks.json")
    products_file = os.path.join(data_root, "products.json")
    task_repo = JsonImageTaskRepository(tasks_file, data_root)

    facade = ImageTaskApplicationService(
        task_repo=task_repo,
        settings_facade=settings_facade,
        event_bus=event_bus,
        data_root=data_root,
        products_file=products_file,
    )

    logger.info("ImageTask domain wired: repos=1")
    return facade


def create_collect_facade(data_root: str, settings_facade, event_bus):
    """装配 Collect 域：仓储 → 事件总线 → 应用服务"""
    from src.serp.collect.domain.events import (
        TaskStarted,
        TaskCompleted as TaskCompletedEvent,
        TaskFailed as TaskFailedEvent,
        TaskDeleted as TaskDeletedEvent,
        ProductSavedFromCollect,
    )
    from src.serp.collect.infrastructure.json_repositories import JsonCollectTaskRepository
    from src.serp.collect.infrastructure import handlers
    from src.serp.collect.application.commands import CollectApplicationService

    # 事件订阅
    event_bus.subscribe(TaskStarted, handlers.log_task_started)
    event_bus.subscribe(TaskCompletedEvent, handlers.log_task_completed)
    event_bus.subscribe(TaskFailedEvent, handlers.log_task_failed)
    event_bus.subscribe(TaskDeletedEvent, handlers.log_task_deleted)
    event_bus.subscribe(ProductSavedFromCollect, handlers.log_product_saved_from_collect)

    tasks_file = os.path.join(data_root, "collect_tasks.json")
    task_repo = JsonCollectTaskRepository(tasks_file)

    facade = CollectApplicationService(
        task_repo=task_repo,
        settings_facade=settings_facade,
        event_bus=event_bus,
        data_root=data_root,
    )

    logger.info("Collect domain wired: repos=1")
    return facade


def create_listing_facade(data_root: str, settings_facade, product_facade, ozon_category_facade, event_bus):
    """装配 Listing 域：仓储 → API/LLM 客户端 → 应用服务 → 蓝图"""
    from src.serp.listing.domain.events import (
        DraftSaved,
        DraftDeleted,
        ListingSimulated,
        ProductImportedToOzon,
        ProductsSynced,
    )
    from src.serp.listing.infrastructure.json_repositories import JsonListingDraftRepository
    from src.serp.listing.infrastructure.ozon_api import OzonApiClient
    from src.serp.listing.infrastructure.autofill_client import DeepSeekAutoFillClient
    from src.serp.listing.infrastructure import handlers
    from src.serp.listing.application.commands import ListingApplicationService
    from src.serp.settings.infrastructure.json_repositories import JsonStoreRepository

    # 事件订阅
    event_bus.subscribe(DraftSaved, handlers.log_draft_saved)
    event_bus.subscribe(DraftDeleted, handlers.log_draft_deleted)
    event_bus.subscribe(ListingSimulated, handlers.log_listing_simulated)
    event_bus.subscribe(ProductImportedToOzon, handlers.log_product_imported)
    event_bus.subscribe(ProductsSynced, handlers.log_products_synced)

    # 仓储
    listings_dir = os.path.join(data_root, "listings")
    draft_repo = JsonListingDraftRepository(listings_dir)

    # Ozon API 凭证获取器（使用 StoreRepository 读取原始凭证）
    store_repo = JsonStoreRepository(os.path.join(data_root, "stores.json"))

    def _get_ozon_credentials(store_id: str) -> tuple[str, str]:
        """从 StoreRepository 获取原始凭证，解析 ${VAR} 占位符"""
        import re as _re
        store = store_repo.find_by_id(store_id)
        if store is None:
            return "", ""
        client_id = str(store.client_id or "")
        api_key = str(store.api_key or "")
        def _resolve_env(value: str) -> str:
            if not value:
                return ""
            def _replace(match):
                var_name = match.group(1)
                return os.environ.get(var_name, match.group(0))
            return _re.sub(r'\$\{([^}]+)\}', _replace, value)
        return _resolve_env(client_id), _resolve_env(api_key)

    # API 客户端
    ozon_api = OzonApiClient(_get_ozon_credentials)

    # DeepSeek 自动填充客户端
    autofill_client = DeepSeekAutoFillClient.resolve(settings_facade, "ozon_attribute_fill")

    # 应用服务
    facade = ListingApplicationService(
        draft_repo=draft_repo,
        ozon_api=ozon_api,
        autofill_client=autofill_client,
        settings_facade=settings_facade,
        product_facade=product_facade,
        ozon_category_facade=ozon_category_facade,
        event_bus=event_bus,
        data_root=data_root,
    )

    logger.info("Listing domain wired: ozon_api=%s, autofill=%s",
                ozon_api.__class__.__name__, autofill_client.model)
    return facade


def create_registry() -> FacadeRegistry:
    return FacadeRegistry()
