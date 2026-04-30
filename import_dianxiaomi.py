"""
店小秘采集数据导入工具

用法:
    python import_dianxiaomi.py <HAR文件路径>
    python import_dianxiaomi.py <HAR文件路径> --base-url <sERP地址>

从 Chrome DevTools 导出的 HAR 文件中提取店小秘采集插件的数据，
转换成 sERP 的采集任务格式，包含产品数据和图片。

操作步骤:
    1. 打开 Chrome DevTools → Network 面板 → 勾选 "Preserve log"
    2. 用店小秘插件采集一个商品
    3. 在网络请求中找到发往 dianxiaomi.com 的 POST 请求
    4. 右键任意请求 → "Save all as HAR with content"
    5. 运行: python import_dianxiaomi.py xxx.har
"""

import json
import os
import re
import sys
import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_ROOT = PROJECT_ROOT / "data"

# ==================== 店小秘字段名映射 ====================
# 店小秘 API 字段 → sERP product_data 字段
FIELD_MAP = {
    # 基本信息
    "title": "title",
    "name": "title",
    "productName": "title",
    "product_name": "title",
    "goodName": "title",
    "goodsName": "title",
    "itemName": "title",
    "subject": "title",
    # 副标题
    "subtitle": "subtitle",
    "subTitle": "subtitle",
    "sub_title": "subtitle",
    "shortDescription": "subtitle",
    # 描述
    "description": "description",
    "detail": "description",
    "desc": "description",
    "productDesc": "description",
    "productDescription": "description",
    "goodsDesc": "description",
    "content": "description",
    # 价格
    "price": "price",
    "salePrice": "price",
    "sale_price": "price",
    "currentPrice": "price",
    "current_price": "price",
    "discountPrice": "price",
    "originalPrice": "original_price",
    "original_price": "original_price",
    "marketPrice": "original_price",
    "regularPrice": "original_price",
    # SKU
    "sku": "sku",
    "skuCode": "sku",
    "sku_code": "sku",
    "productSku": "sku",
    "sellerSku": "sku",
    "asin": "asin",
    "ASIN": "asin",
    "productId": "product_id",
    "product_id": "product_id",
    "itemId": "product_id",
    "item_id": "product_id",
    "goodId": "product_id",
    "goodsId": "product_id",
    # 平台
    "platform": "platform",
    "source": "platform",
    "site": "platform",
    "website": "platform",
    "marketplace": "platform",
    # URL
    "url": "source_url",
    "link": "source_url",
    "productUrl": "source_url",
    "product_url": "source_url",
    "detailUrl": "source_url",
    "detail_url": "source_url",
    "sourceUrl": "source_url",
    # 品牌
    "brand": "brand",
    "brandName": "brand",
    "brand_name": "brand",
    # 分类
    "category": "category",
    "categoryName": "category",
    "category_name": "category",
    "categoryPath": "category",
    # 属性
    "attributes": "attributes",
    "props": "attributes",
    "properties": "attributes",
    "specs": "attributes",
    "specifications": "attributes",
    # 图片
    "images": "images",
    "pictures": "images",
    "imageList": "images",
    "image_list": "images",
    "imageUrls": "images",
    "image_urls": "images",
    "productImages": "images",
    "mainImages": "images",
    "mainImage": "images",
    "photos": "images",
    "gallery": "images",
    "picList": "images",
    "pic_list": "images",
    # 变种
    "variants": "variants",
    "variations": "variants",
    "skus": "variants",
    "skuList": "variants",
    "sku_list": "variants",
    "specList": "variants",
    "spec_list": "variants",
    "colorImages": "variant_images",
    "color_images": "variant_images",
    "variantImages": "variant_images",
    "variant_images": "variant_images",
    # 变种内部字段
    "variantName": "name",
    "variant_name": "name",
    "variantTitle": "name",
    "variantValue": "value",
    "variant_value": "value",
    "specName": "name",
    "specValue": "value",
    "color": "name",
    "colorName": "name",
    "size": "value",
    "sizeName": "value",
    "variantPrice": "price",
    "variant_price": "price",
    "variantSku": "sku",
    "variant_sku": "sku",
    "variantImage": "image",
    "variant_image": "image",
    "variantStock": "stock",
    "variant_stock": "stock",
}


def _deep_get(obj, *keys):
    """深度获取字典中的值，支持多级 key"""
    for key in keys:
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj


def _parse_har(filepath: str) -> dict:
    """读取并解析 HAR 文件"""
    with open(filepath, "r", encoding="utf-8") as f:
        har = json.load(f)
    if "log" not in har:
        raise ValueError("无效的 HAR 文件：缺少顶层 'log' 键")
    return har


def _extract_dianxiaomi_entries(har: dict) -> list[dict]:
    """从 HAR 中提取所有发往店小秘的请求"""
    entries = []
    for entry in har.get("log", {}).get("entries", []):
        url = entry.get("request", {}).get("url", "")
        if "dianxiaomi.com" in url:
            entries.append(entry)
    return entries


def _extract_json_body(entry: dict) -> dict | None:
    """从 entry 的 request body 或 response body 中提取 JSON"""
    # 先试 request body
    post_data = _deep_get(entry, "request", "postData", "text")
    if post_data:
        try:
            data = json.loads(post_data)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass

    # 再试 response body
    resp_text = _deep_get(entry, "response", "content", "text")
    if resp_text:
        try:
            data = json.loads(resp_text)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def _flatten_dict(d: dict, prefix: str = "") -> dict:
    """展平嵌套字典，用于字段探测"""
    result = {}
    if isinstance(d, dict):
        for k, v in d.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                result.update(_flatten_dict(v, new_key))
            elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                # 取第一个元素探测
                result.update(_flatten_dict(v[0], f"{new_key}[]"))
            else:
                result[new_key] = v
    return result


def _is_product_data(obj: dict) -> bool:
    """试探：是否是产品数据（至少包含标题或图片）"""
    flat = _flatten_dict(obj)
    flat_lower = {k.lower(): v for k, v in flat.items()}
    keys = flat_lower.keys()
    has_title = any(
        kw in k for kw in ("title", "name", "productname", "goodname", "itemname")
        for k in keys
    )
    has_images = any(
        kw in k for kw in ("images", "image", "picture", "photo", "pic")
        for k in keys
    )
    has_price = any(
        kw in k for kw in ("price", "saleprice", "amount")
        for k in keys
    )
    # 至少满足两条才认为是产品数据
    score = sum([has_title, has_images, has_price])
    return score >= 2


def _extract_product_fields(obj: dict) -> dict:
    """从 JSON 对象中提取产品字段，返回标准化 dict"""
    # 先展平
    flat = _flatten_dict(obj)
    # 也保留原始对象用于提取列表字段（images、variants）
    product = {}
    extracted_keys = set()

    # 先处理展平字段
    for key, value in flat.items():
        if value is None or value == "":
            continue
        # 尝试映射
        key_lower = key.lower()
        # 提取最后一段 key name
        key_last = key_lower.rsplit(".", 1)[-1].rstrip("[]")

        mapped = None
        # 精确匹配
        for dk, sv in FIELD_MAP.items():
            if dk.lower() == key_last or dk.lower() == key_lower:
                mapped = sv
                break
        # 模糊匹配
        if not mapped:
            for dk, sv in FIELD_MAP.items():
                if dk.lower() in key_last or key_last in dk.lower():
                    mapped = sv
                    break

        if mapped and mapped not in extracted_keys:
            product[mapped] = value
            extracted_keys.add(mapped)

    # 特殊处理：从原始对象提取 images 数组
    images = _extract_images_array(obj)
    if images:
        product["images"] = images

    # 特殊处理：从原始对象提取 variants 数组
    variants = _extract_variants_array(obj)
    if variants:
        product["variants"] = variants

    return product


def _extract_images_array(obj: dict) -> list[str]:
    """从 JSON 对象中提取图片 URL 列表"""
    image_keys = [
        "images", "pictures", "imageList", "image_list",
        "imageUrls", "image_urls", "productImages", "mainImages",
        "photos", "gallery", "picList", "pic_list", "mainImage",
    ]

    for key in image_keys:
        val = obj.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return [val]
        if isinstance(val, list) and len(val) > 0:
            # 可能是字符串 URL 列表
            if isinstance(val[0], str):
                return [u for u in val if isinstance(u, str) and u.startswith("http")]
            # 可能是对象列表（含 url/src 字段）
            if isinstance(val[0], dict):
                urls = []
                for item in val:
                    for img_k in ("url", "src", "imageUrl", "image_url", "large", "hiRes", "original", "big"):
                        if img_k in item and isinstance(item[img_k], str) and item[img_k].startswith("http"):
                            urls.append(item[img_k])
                            break
                if urls:
                    return urls

        # 嵌套一层
        if isinstance(val, dict):
            for sub_key in image_keys:
                sub_val = val.get(sub_key)
                if isinstance(sub_val, list) and len(sub_val) > 0:
                    if isinstance(sub_val[0], str):
                        return [u for u in sub_val if isinstance(u, str) and u.startswith("http")]
                    if isinstance(sub_val[0], dict):
                        urls = []
                        for item in sub_val:
                            for img_k in ("url", "src", "imageUrl", "hiRes", "large"):
                                if img_k in item and isinstance(item[img_k], str):
                                    urls.append(item[img_k])
                                    break
                        if urls:
                            return urls

    # 兜底：递归查找所有 http URL
    found_urls = _find_image_urls_in_obj(obj)
    if found_urls:
        return found_urls[:50]

    return []


def _find_image_urls_in_obj(obj, depth=0, max_depth=5) -> list[str]:
    """递归查找对象中的图片 URL"""
    urls = []
    if depth > max_depth:
        return urls
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("http") and _looks_like_image_url(v):
                urls.append(v)
            elif isinstance(v, (dict, list)):
                urls.extend(_find_image_urls_in_obj(v, depth + 1, max_depth))
    elif isinstance(obj, list):
        for item in obj:
            urls.extend(_find_image_urls_in_obj(item, depth + 1, max_depth))
    return urls


def _looks_like_image_url(url: str) -> bool:
    """判断 URL 是否像图片"""
    url_lower = url.lower()
    # 排除明显的非图片 URL
    exclusions = [
        "analytics", "pixel", "tracking", "beacon", "logo", "icon", "avatar",
        "favicon", "banner", "advertisement", ".js", ".css", ".html",
    ]
    for ex in exclusions:
        if ex in url_lower:
            return False
    # 图片扩展名或常见 CDN 模式
    img_patterns = [
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff",
        "/images/", "/image/", "/img/", "/photo/", "/picture/",
        "amazon.com/images/I/", "ozon.ru", "wbbasket",
        "_AC_", "_SL", "_SX", "_SY", "_SR",
    ]
    for pat in img_patterns:
        if pat in url_lower:
            return True
    return False


def _extract_variants_array(obj: dict) -> list[dict]:
    """从 JSON 对象中提取变种列表"""
    variant_keys = [
        "variants", "variations", "skus", "skuList", "sku_list",
        "specList", "spec_list", "colorImages", "color_images",
    ]

    for key in variant_keys:
        val = obj.get(key)
        if isinstance(val, list) and len(val) > 0:
            result = []
            for item in val:
                if isinstance(item, dict):
                    normalized = {}
                    for k, v in item.items():
                        mapped = FIELD_MAP.get(k) or FIELD_MAP.get(k.lower())
                        if mapped:
                            normalized[mapped] = v
                        elif isinstance(v, (str, int, float, bool)):
                            normalized[k] = v
                    if normalized:
                        result.append(normalized)
                elif isinstance(item, str):
                    result.append({"name": item})
            if result:
                return result
        elif isinstance(val, dict) and len(val) > 0:
            # colorImages 格式: {colorName: [urls]}
            result = []
            for vname, vdata in val.items():
                if isinstance(vdata, list):
                    result.append({"name": vname, "images": vdata})
                else:
                    result.append({"name": vname, "data": vdata})
            if result:
                return result

    return []


def _detect_platform(data: dict) -> str:
    """从数据中推测平台"""
    # 先检查显式的 platform 字段
    platform = data.get("platform", "").lower()
    if "amazon" in platform:
        return "amazon"
    if "ozon" in platform:
        return "ozon"
    if "wildberries" in platform or "wb" == platform:
        return "wildberries"

    # 从 URL 推测
    url = data.get("source_url", "").lower()
    if "amazon" in url:
        return "amazon"
    if "ozon" in url:
        return "ozon"
    if "wildberries" in url:
        return "wildberries"

    return platform or "unknown"


def _sanitize_filename(name: str) -> str:
    """清理文件名"""
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    if len(name) > 80:
        name = name[:80]
    return name


def _download_image(url: str, save_dir: Path, index: int) -> str | None:
    """下载单张图片，返回文件名"""
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    # 确定扩展名
    ext = ".jpg"
    url_lower = url.split("?")[0].lower()
    for e in (".png", ".webp", ".gif", ".jpeg", ".bmp"):
        if e in url_lower:
            ext = e
            break

    filename = f"img_{index:04d}{ext}"
    filepath = save_dir / filename

    if filepath.exists():
        return filename

    try:
        # 尝试代理
        proxies = None
        proxy_url = os.getenv("PROXY")
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}

        resp = requests.get(url, headers=headers, proxies=proxies, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 1000:
            filepath.write_bytes(resp.content)
            return filename
    except Exception as e:
        print(f"  ⚠ 下载失败 {url[:80]}: {e}")

    return None


def import_from_har(
    har_path: str,
    base_url: str = "http://127.0.0.1:5000",
    download_images: bool = True,
) -> dict:
    """
    从 HAR 文件导入店小秘采集数据。

    返回:
        {task_id, product_data, images_count, ...}
    """
    print(f"📂 读取 HAR 文件: {har_path}")
    har = _parse_har(har_path)

    print(f"🔍 搜索店小秘 API 请求...")
    entries = _extract_dianxiaomi_entries(har)
    print(f"  找到 {len(entries)} 个相关请求")

    if not entries:
        print("❌ 未找到店小秘相关请求，请确认 HAR 文件包含 dianxiaomi.com 的记录")
        return None

    # 按请求大小排序（产品数据通常在较大的请求中）
    entries.sort(
        key=lambda e: len(str(e)),
        reverse=True,
    )

    # 寻找包含产品数据的请求
    product_data = None
    best_entry = None

    for entry in entries:
        body = _extract_json_body(entry)
        if body and _is_product_data(body):
            product_data = _extract_product_fields(body)
            best_entry = entry
            print(f"  ✅ 从 {entry['request']['url'][:100]} 提取产品数据")
            break

    if not product_data or not product_data.get("title"):
        # 尝试从所有请求中合并数据
        print("  ⚠ 未找到明确产品数据，尝试从所有请求提取...")
        for entry in entries:
            body = _extract_json_body(entry)
            if body:
                fields = _extract_product_fields(body)
                if fields.get("title") or fields.get("images"):
                    product_data = fields
                    best_entry = entry
                    break

    if not product_data:
        print("❌ 未能从 HAR 中提取产品数据")
        print("  → 请检查 HAR 文件是否包含 content（导出时勾选 Save as HAR with content）")
        return None

    # 补充字段
    platform = _detect_platform(product_data)
    product_data["platform"] = platform

    # 生成 task_id
    title_hash = hashlib.md5(
        (product_data.get("title") or product_data.get("source_url") or "unknown").encode()
    ).hexdigest()[:8]
    task_id = f"collect_{title_hash}"
    product_data["task_id"] = task_id

    # 创建采集目录
    from collector import _get_collect_dir
    collect_dir = Path(_get_collect_dir(task_id))
    collect_dir.mkdir(parents=True, exist_ok=True)

    # 下载图片
    images = product_data.pop("images", [])
    variants = product_data.pop("variants", None)

    images_count = len(images)
    downloaded_count = 0

    if download_images and images:
        images_dir = collect_dir / "images"
        images_dir.mkdir(exist_ok=True)
        print(f"\n📥 下载 {len(images)} 张图片...")

        images_mapping = []
        for i, url in enumerate(images):
            filename = _download_image(url, images_dir, i + 1)
            success = filename is not None
            if success:
                downloaded_count += 1
            images_mapping.append({
                "original_url": url,
                "new_name": filename,
                "success": success,
                "category": "product",
            })
            if (i + 1) % 5 == 0:
                print(f"  进度: {i+1}/{len(images)}")

        # 保存 images_mapping.json
        with open(collect_dir / "images_mapping.json", "w", encoding="utf-8") as f:
            json.dump(images_mapping, f, indent=2, ensure_ascii=False)

    # 构建 variant_images 结构（如果有变种数据）
    variant_images = {}
    if variants:
        for v in variants:
            vname = v.get("name") or v.get("value") or f"variant_{len(variant_images)}"
            vimgs = v.pop("images", []) if isinstance(v, dict) else []
            if isinstance(vimgs, list):
                variant_images[vname] = vimgs

    # 保存 product_data.json
    product_output = {**product_data}
    if variant_images:
        product_output["variant_images"] = variant_images
    if variants:
        product_output["variants"] = variants

    with open(collect_dir / "product_data.json", "w", encoding="utf-8") as f:
        json.dump(product_output, f, indent=2, ensure_ascii=False)

    # 注册到 collect_tasks（写入持久化文件）
    tasks_file = DATA_ROOT / "collect_tasks.json"
    tasks = {}
    if tasks_file.exists():
        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                tasks = json.load(f)
        except:
            pass

    tasks[task_id] = {
        "status": "completed",
        "progress": 100,
        "message": f"从店小秘HAR导入完成 — {product_data.get('title', '未知')[:30]}",
        "result": {
            "title": product_data.get("title", "未知"),
            "platform": platform,
            "url": product_data.get("source_url", ""),
            "image_count": images_count,
            "downloaded": downloaded_count,
            "failed": images_count - downloaded_count,
            "product_data": str(collect_dir / "product_data.json"),
            "images_mapping": str(collect_dir / "images_mapping.json") if download_images else None,
            "source": "dianxiaomi_har",
        },
    }

    with open(tasks_file, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

    # 打印摘要
    print(f"\n{'='*50}")
    print(f"✅ 导入完成!")
    print(f"{'='*50}")
    print(f"  Task ID:     {task_id}")
    print(f"  标题:        {product_data.get('title', '未知')[:60]}")
    print(f"  平台:        {platform}")
    print(f"  图片:        {downloaded_count}/{images_count} 张已下载")
    if variant_images:
        print(f"  变种:        {len(variant_images)} 个颜色/规格")
    print(f"  数据目录:    {collect_dir}")
    print(f"  原始 URL:    {product_data.get('source_url', '未知')}")
    print(f"\n  → 启动 sERP 后可在采集卡片中查看")

    return {
        "task_id": task_id,
        "product_data": product_output,
        "images_count": images_count,
        "downloaded_count": downloaded_count,
    }


# ==================== HTML Debug: 直接解析店小秘页面 ====================

def _parse_dianxiaomi_html(html_path: str) -> dict | None:
    """从店小秘产品添加页面的 HTML 中提取已有数据（作为无 HAR 时的替代方案）

    解析的是店小秘「添加Ozon产品」页面的 DOM 数据：
    - 已填好的表单字段（标题、价格、描述等）
    - 已上传的图片 URL
    - 已选的品类
    """
    from bs4 import BeautifulSoup

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, 'html.parser')
    product = {}

    # 尝试从 Vue 组件的 data 属性提取
    for script in soup.find_all("script"):
        text = script.string or ""
        if "productName" in text or "goodsName" in text:
            # 尝试提取 JSON
            for match in re.finditer(r'"productName"\s*:\s*"([^"]*)"', text):
                product["title"] = match.group(1)
            for match in re.finditer(r'"goodsName"\s*:\s*"([^"]*)"', text):
                product["title"] = product.get("title") or match.group(1)
            for match in re.finditer(r'"price"\s*:\s*([\d.]+)', text):
                product["price"] = float(match.group(1))
            for match in re.finditer(r'"images"\s*:\s*(\[.*?\])', text):
                try:
                    product["images"] = json.loads(match.group(1))
                except:
                    pass

    return product if product.get("title") else None


# ==================== CLI ====================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    har_path = sys.argv[1]
    base_url = "http://127.0.0.1:5000"
    download = True

    for arg in sys.argv[2:]:
        if arg.startswith("--base-url="):
            base_url = arg.split("=", 1)[1]
        elif arg == "--no-download":
            download = False

    if not os.path.exists(har_path):
        print(f"❌ 文件不存在: {har_path}")
        sys.exit(1)

    result = import_from_har(har_path, base_url, download_images=download)
    if result:
        print(f"\n刷新 sERP 页面即可看到导入的采集卡片。")
