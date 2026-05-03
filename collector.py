"""
采集产品模块 - 三层架构
1. 抓取层 (Crawl4AI) - 智能识别商品页面结构
2. 决策层 (DeepSeek-V4) - 图片分类与重命名
3. 执行层 (异步下载 + Pillow 转 JPG)
"""

import os
import json
import re
import asyncio
import logging
import aiohttp
from datetime import datetime
from urllib.parse import urlparse
from PIL import Image
import io

logger = logging.getLogger(__name__)

# ---------- 配置 ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
CONCURRENT_DOWNLOADS = 5  # 并发下载数
DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PROXY_URL = os.getenv("PROXY", "http://127.0.0.1:7890")  # Clash 本地代理地址
PROXY_ENABLED = os.getenv("PROXY_ENABLED", "true").lower() == "true"

# ---------- 工具函数 ----------

def _extract_platform(url: str) -> str:
    """从URL中提取平台名称"""
    domain = urlparse(url).netloc.lower()
    if "ozon" in domain:
        return "ozon"
    elif "wildberries" in domain or "wb" in domain:
        return "wildberries"
    elif "amazon" in domain:
        return "amazon"
    elif "yandex" in domain or "market" in domain:
        return "yandex"
    else:
        return "unknown"


def _sanitize_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def _get_collect_dir(task_id: str) -> str:
    """获取采集任务的数据目录"""
    return os.path.join(DATA_ROOT, f"collect_{task_id}")


def _get_proxy_dict() -> dict | None:
    """获取 requests 格式的代理配置。"""
    if not PROXY_ENABLED or not PROXY_URL:
        return None
    return {"http": PROXY_URL, "https": PROXY_URL}


def _get_proxy_server() -> str | None:
    """获取 Playwright/aiohttp 格式的代理地址。"""
    if not PROXY_ENABLED or not PROXY_URL:
        return None
    return PROXY_URL


# ==================== 第一层：抓取层 (Playwright + requests 双引擎) ====================

import requests as sync_requests


def _fetch_html_requests(url: str) -> str:
    """使用 requests 获取页面 HTML（快速模式）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "max-age=0",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
    }
    proxies = _get_proxy_dict()
    resp = sync_requests.get(url, headers=headers, timeout=30, allow_redirects=True, proxies=proxies)
    resp.raise_for_status()
    return resp.text


async def _fetch_html_playwright(url: str) -> str:
    """使用 Playwright 获取页面 HTML（支持 JS 渲染，含反爬措施）"""
    import random as _random
    try:
        from playwright.async_api import async_playwright
        proxy_server = _get_proxy_server()
        async with async_playwright() as p:
            launch_args = [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--disable-blink-features=AutomationControlled',
            ]
            if proxy_server:
                launch_args.append(f'--proxy-server={proxy_server}')
            browser = await p.chromium.launch(
                headless=True,
                args=launch_args,
            )
            context_options = {
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "viewport": {"width": 1920, "height": 1080},
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
            }
            if proxy_server:
                context_options["proxy"] = {"server": proxy_server}
            context = await browser.new_context(**context_options)
            page = await context.new_page()

            # 隐藏自动化特征
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            """)

            page.set_default_timeout(25000)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 模拟人类浏览：随机等待 2-5 秒
                await page.wait_for_timeout(2000 + int(_random.random() * 3000))
            except Exception as e:
                logger.warning("Playwright 页面加载超时，继续处理已有内容: %s", e)
                await page.wait_for_timeout(3000)

            html = await page.content()

            # 检测是否遇到验证页面
            if _is_blocked(html):
                logger.error("检测到反爬验证页面 (CAPTCHA/block)")
                raise Exception("遇到反爬验证页面，请稍后重试或更换 IP")

            await browser.close()
            return html
    except Exception as e:
        if "反爬验证" in str(e):
            raise
        raise Exception(f"Playwright 抓取失败: {str(e)}")


def _is_blocked(html: str) -> bool:
    """检测是否被反爬拦截"""
    # 页面太小 → 大概率是被拦截的占位页
    if len(html) < 8000:
        return True
    blockers = [
        'Type the characters you see in this image',
        'Enter the characters you see below',
        'robot check',
        'g-recaptcha',
        'captcha',
        'To discuss automated access',
        'Sorry, we just need to make sure',
        'rd-script-',              # Amazon CAPTCHA script reference
        'api/pvov',                # Amazon verification endpoint
    ]
    lower = html.lower()
    return any(b.lower() in lower for b in blockers)


async def _fetch_html(url: str) -> str:
    """智能获取页面 HTML。

    引擎选择策略：
    - Amazon: requests 优先（反爬较轻，Playwright 易触发 CAPTCHA）
    - Wildberries/Ozon: Playwright（JS 渲染必需）
    - 其他: requests 优先
    - 任何引擎失败后尝试另一个
    """
    platform = _extract_platform(url)

    # Amazon 用 requests 优先（Playwright headless 极易触发 CAPTCHA）
    if platform == 'amazon':
        try:
            logger.info("使用 requests 抓取 (Amazon 优先)")
            html = _fetch_html_requests(url)
            if _is_blocked(html):
                logger.warning("Requests 遇到反爬拦截 (页面大小=%d)，回退到 Playwright", len(html))
                return await _fetch_html_playwright(url)
            return html
        except Exception as e:
            logger.warning("Requests 抓取 Amazon 失败，尝试 Playwright: %s", e)
            return await _fetch_html_playwright(url)

    # Wildberries/Ozon 需要 JS 渲染
    if platform in ('wildberries', 'ozon'):
        try:
            logger.info("使用 Playwright 抓取 (平台: %s)", platform)
            return await _fetch_html_playwright(url)
        except Exception as e:
            logger.warning("Playwright 抓取失败，尝试 requests: %s", e)
            return _fetch_html_requests(url)

    # 其他平台：requests 优先
    try:
        return _fetch_html_requests(url)
    except Exception as e:
        logger.warning("Requests 抓取失败，尝试 Playwright: %s", e)
        return await _fetch_html_playwright(url)


def _extract_amazon_variant_images(soup) -> dict:
    """从 Amazon 页面提取按变体（颜色/尺寸）分组的图片集。

    主要数据源：<script> 标签中的 colorImages JavaScript 对象。
    结构：{ 'colorImages': { 'initial': [...], 'Black': [...], 'Blue': [...] } }
    辅以 colorAsin 映射 ASIN→颜色名。
    """
    variant_images = {}

    for script in soup.find_all('script'):
        text = script.string or ''
        if 'colorImages' not in text:
            continue

        # 定位 colorImages 对象
        match = re.search(r'["\']colorImages["\']\s*:\s*\{', text)
        if not match:
            continue

        # 括号匹配提取完整 JSON 对象
        start = match.end() - 1
        depth = 0
        end = start
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"' or c == "'":
                if not in_string:
                    in_string = c
                elif in_string == c:
                    in_string = False
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        json_str = text[start:end]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            continue

        # 提取 colorAsin 映射（ASIN → 颜色名）
        color_asin = {}
        asin_match = re.search(r'["\']colorAsin["\']\s*:\s*\{', text)
        if asin_match:
            as_start = asin_match.end() - 1
            depth2 = 0
            as_end = as_start
            in_string2 = False
            escape2 = False
            for i in range(as_start, min(len(text), as_start + 5000)):
                c = text[i]
                if escape2:
                    escape2 = False
                    continue
                if c == '\\':
                    escape2 = True
                    continue
                if c == '"' or c == "'":
                    if not in_string2:
                        in_string2 = c
                    elif in_string2 == c:
                        in_string2 = False
                    continue
                if in_string2:
                    continue
                if c == '{':
                    depth2 += 1
                elif c == '}':
                    depth2 -= 1
                    if depth2 == 0:
                        as_end = i + 1
                        break
            try:
                color_asin = json.loads(text[as_start:as_end])
            except json.JSONDecodeError:
                pass

        # 构建变体名→图片URL列表
        for variant_name, images in data.items():
            if variant_name == 'initial':
                continue
            urls = []
            for img in images:
                if isinstance(img, dict):
                    url = img.get('hiRes') or img.get('large') or ''
                    if not url and isinstance(img.get('main'), dict):
                        url = img['main'].get('url', '')
                    if url and url.startswith('http'):
                        urls.append(url)
            if urls:
                name = variant_name.strip()
                # 如果是 ASIN，尝试映射为颜色名
                if name.startswith('B0') and name in color_asin:
                    continue  # ASIN 键由颜色名键覆盖
                # 反向：用 colorAsin 的值匹配
                for cname, casin in color_asin.items():
                    if casin == name:
                        name = cname
                        break
                variant_images[name] = urls

        if variant_images:
            break

    # 回退：从 swatch 元素提取
    if not variant_images:
        variant_images = _extract_swatch_images(soup)

    return variant_images


def _extract_swatch_images(soup) -> dict:
    """从色板/swatch DOM 元素提取变体图片（回退方案）"""
    variant_images = {}

    # Amazon swatch 选择器
    swatch_selectors = [
        'li[data-dp-url]',
        'li.imageSwatch img',
        '#twisterContainer li img',
        '#variation_color_name li img',
        '.swatchAvailable img',
        'img.imgSwatch',
    ]
    seen_urls = set()
    for selector in swatch_selectors:
        for el in soup.select(selector):
            src = el.get('src') or el.get('data-src') or ''
            alt = (el.get('alt') or el.get('title') or '').strip()
            if src and src.startswith('http'):
                src_base = _normalize_img_url(src)
                if src_base in seen_urls:
                    continue
                seen_urls.add(src_base)
                name = alt or f"variant_{len(variant_images) + 1}"
                # 提取颜色描述
                for prefix in ['选择 ', 'Select ', 'Click to select ', 'Color: ']:
                    name = name.replace(prefix, '')
                variant_images.setdefault(name, []).append(src)

    return variant_images


def _extract_wildberries_variants(html: str, soup) -> dict:
    """从 Wildberries 页面提取变体图片。

    数据通常在 __NUXT__ 或 __APP__ JS 变量中，或 <script type=application/ld+json>。
    """
    variant_images = {}

    # 方法1: 从 JSON-LD 提取 (schema.org/Product)
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                # 变体数据可能在 offers 中
                offers = data.get('offers', [])
                if isinstance(offers, dict):
                    offers = [offers]
                for offer in offers:
                    color = offer.get('color', '') or offer.get('name', '')
                    img = offer.get('image', '')
                    if color and img:
                        variant_images.setdefault(color, []).append(img)
                if variant_images:
                    return variant_images
        except:
            pass

    # 方法2: 从 __NUXT__ / __APP__ 提取
    for pattern in [r'window\.__NUXT__\s*=\s*(\{.*?\});', r'window\.__APP__\s*=\s*(\{.*?\});']:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                # 遍历查找含 variant/images 的结构
                _walk_wb_variants(data, variant_images)
                if variant_images:
                    return variant_images
            except:
                continue

    # 方法3: 从色板/选项 DOM 元素提取
    # WB 颜色选择器通常在 .j-color-list 或 .color-list 中
    wb_swatch_selectors = [
        '.j-color-list .j-img',
        '.color-list img',
        '#colorpicker img',
        '.product-options img',
        '[data-color] img',
    ]
    for selector in wb_swatch_selectors:
        for el in soup.select(selector):
            src = el.get('src') or el.get('data-src') or ''
            color = (el.get('alt') or el.get('title') or
                     el.parent.get('data-color', '') if el.parent else '')
            if src and 'http' in src:
                color = color.strip() or f"variant_{len(variant_images) + 1}"
                variant_images.setdefault(color, []).append(_normalize_img_url(src))

    return variant_images


def _walk_wb_variants(data, out: dict):
    """递归遍历 Wildberries 数据对象，提取变体图片信息。"""
    if isinstance(data, dict):
        # 查找 nomenclatures / products / variants 等关键字段
        for key in ('nomenclatures', 'products', 'variants', 'colors', 'colorVariants'):
            items = data.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        name = item.get('name', '') or item.get('color', '') or item.get('colorName', '')
                        images = item.get('images', []) or item.get('photos', [])
                        if isinstance(images, list) and name:
                            urls = []
                            for img in images:
                                if isinstance(img, dict):
                                    u = img.get('url', '') or img.get('big', '') or img.get('original', '')
                                    if u:
                                        urls.append(u)
                                elif isinstance(img, str):
                                    urls.append(img)
                            if urls:
                                out[name.strip()] = urls
        # 递归子对象
        for v in data.values():
            _walk_wb_variants(v, out)
    elif isinstance(data, list):
        for item in data:
            _walk_wb_variants(item, out)


def _normalize_img_url(url: str) -> str:
    """标准化图片 URL：去掉查询参数和尺寸后缀，便于比较。"""
    if url.startswith('//'):
        url = 'https:' + url
    # 去掉 ? 后参数
    url = url.split('?')[0]
    return url


def _is_noise_image(src: str) -> bool:
    """判断图片是否为无关噪声（图标/badge/像素/spacer/缩略图等）。"""
    src_lower = src.lower()
    noise_patterns = [
        # 功能性图标
        'icon', 'avatar', 'logo', 'spacer', 'pixel', '1x1', 'flag',
        'badge', 'transparent', 'blank', 'grey', 'placeholder',
        'sprite', 'dot', 'loading', 'ajax-loader', 'spinner',
        'star', 'rating', 'review', 'vote',
        # SVG 图标
        '.svg',
        # 色板/缩略图
        'swatch', 'color-picker',
        # 亚马逊尺寸标识（小图：后缀含 _SR / _SS / _UL + 数字）
        '_SR75', '_SR100', '_SR166', '_SR200',
        '_SS40_', '_SS50_', '_SS60_', '_SS70_', '_SS75_', '_SS100_', '_SS180_',
        '_AC_SR', '_AC_SS', '_AC_UL',
        # WB 缩略图标识
        '_thumbnail', '_small', '__small',
        # 亚马逊 A+ 内容装饰图
        'aplus-media-library',
        # 低质量标识
        'QL70_ML2', 'QL75_ML2',
        # 无关域名
        'fls-na.amazon.com', 'pixel.quantserve',
        'bat.bing.com', 'google-analytics',
        # icon 前缀
        'icon_', '_icon', 'thumb-', '-thumb',
    ]
    return any(p in src_lower for p in noise_patterns)


def _filter_image_urls(raw_urls: list) -> list:
    """过滤无关图片：去噪、去重（保留高清版）。"""
    # 1. 去噪
    cleaned = []
    for url in raw_urls:
        if not _is_noise_image(url):
            cleaned.append(url)

    # 2. 提取 Amazon 图片 ID：URL 中 /images/I/{ID}._{SUFFIX}_  → ID 是第一个 ._ 之前的部分
    def _img_id(u):
        u = _normalize_img_url(u)
        fn = u.split('/')[-1]
        # Amazon: IMGID._AC_SX679_.jpg → IMGID
        idx = fn.find('._')
        if idx > 0:
            return fn[:idx]
        return fn

    def _img_resolution(u):
        """估算图片尺寸（从 Amazon URL 后缀提取）。"""
        # 匹配 _SX679, _SY450, _SL1500, _SR165,165, _US40, _UL116 等
        dims = re.findall(r'_[A-Z]{2,3}(\d+(?:,\d+)?)', u)
        total = 0
        for d in dims:
            nums = [int(x) for x in d.split(',')[:2]]
            total += max(nums)
        return total if total > 0 else 0

    # 3. 按图片 ID 去重，保留分辨率最大的版本
    groups = {}
    for url in cleaned:
        key = _img_id(url)
        if key not in groups:
            groups[key] = url
        else:
            if _img_resolution(url) > _img_resolution(groups[key]):
                groups[key] = url

    # 4. 过滤低分辨率（< 200px 通常不是产品图）
    result = []
    for url in groups.values():
        res = _img_resolution(url)
        # 0 = 无法识别分辨率（非Amazon URL），保留
        if res == 0 or res >= 200:
            result.append(url)

    return sorted(result, key=lambda u: _img_resolution(u), reverse=True)


def _extract_from_html(html: str, url: str) -> dict:
    """从 HTML 中提取商品信息"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    platform = _extract_platform(url)

    extracted = {
        "url": url,
        "platform": platform,
        "title": "",
        "price": "",
        "currency": "",
        "attributes": {},
        "description": "",
        "about_item": "",
        "product_description": "",
        "image_urls": [],
        "reviews": [],
        "raw_text_length": len(html),
    }

    # 提取标题
    for tag in ['h1', 'h2', 'title']:
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            text = el.get_text(strip=True)
            if len(text) < 500:
                extracted["title"] = text
                break

    # 提取价格
    price_patterns = [
        'span.a-price span.a-offscreen',
        'span.a-price-whole',
        '.priceToPay span.a-offscreen',
        '[data-a-color="price"] span.a-offscreen',
        '.product-price',
        '.price',
        '[class*="price"]',
    ]
    for pattern in price_patterns:
        if '.' in pattern or '[' in pattern:
            try:
                el = soup.select_one(pattern)
                if el:
                    text = el.get_text(strip=True)
                    if text and ('$' in text or '¥' in text or any(c.isdigit() for c in text)):
                        extracted["price"] = text
                        break
            except:
                pass

    # ===== 图片提取（增强版 — 反爬 + 去噪 + 变体分组） =====
    found_images = set()

    # 1. 从 JSON-LD 结构化数据中提取
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                img_data = data.get('image', [])
                if isinstance(img_data, str):
                    found_images.add(img_data)
                elif isinstance(img_data, list):
                    for img in img_data:
                        if isinstance(img, str):
                            found_images.add(img)
        except:
            pass

    # 2. 从 Open Graph 和 Twitter Card 元数据中提取
    for meta in soup.find_all('meta'):
        prop = (meta.get('property') or meta.get('name') or '').lower()
        content = meta.get('content', '')
        if content and ('image' in prop or 'photo' in prop):
            if content.startswith('http'):
                found_images.add(content)

    # 3. 从平台特定选择器提取
    if platform == 'amazon':
        amazon_selectors = [
            'div#imgTagWrapperId img',
            'div.imgTagWrapper img',
            '#landingImage',
            '#imgBlkFront',
            '.a-dynamic-image',
            'div#imageBlock img',
            'img[data-old-hires]',
            'img[data-a-dynamic-image]',
            'li.image img',
            '.imageThumbnail img',
            'div[data-component="imageBlock"] img',
        ]
        for selector in amazon_selectors:
            try:
                for img in soup.select(selector):
                    for attr in ['src', 'data-src', 'data-old-hires']:
                        src = img.get(attr, '')
                        if src and not _is_noise_image(src):
                            if src.startswith('//'):
                                src = 'https:' + src
                            found_images.add(src)
                            break
            except:
                pass
    elif platform == 'wildberries':
        wb_selectors = [
            '.j-zoom-image',
            '.product-page__gallery img',
            '.swiper-zoom-container img',
            '.j- product-photo img',
            'img.j-product-photo',
        ]
        for selector in wb_selectors:
            try:
                for img in soup.select(selector):
                    src = img.get('src') or img.get('data-src') or img.get('data-original') or ''
                    if src and not _is_noise_image(src):
                        if src.startswith('//'):
                            src = 'https:' + src
                        found_images.add(src)
            except:
                pass

    # 4. 从所有 img 标签提取（使用增强的噪声过滤）
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-old-hires') or img.get('data-original') or ''
        if not src:
            continue
        if _is_noise_image(src):
            continue
        if src.startswith('//'):
            src = 'https:' + src
        elif src.startswith('/'):
            parsed = urlparse(url)
            src = f"{parsed.scheme}://{parsed.netloc}{src}"
        found_images.add(src)

    # 5. 从内联 CSS background-image 中提取
    for tag in soup.find_all(style=True):
        style = tag['style']
        bg_match = re.search(r'background(?:-image)?\s*:\s*url\([\'"]?(https?://[^\'")\s]+)[\'"]?\)', style)
        if bg_match:
            found_images.add(bg_match.group(1))

    # 6. 从 data 属性中提取图片 URL（Amazon 特有：含全分辨率映射）
    for tag in soup.find_all(attrs={"data-a-dynamic-image": True}):
        try:
            dynamic_data = json.loads(tag["data-a-dynamic-image"])
            for url_key in dynamic_data.keys():
                if url_key.startswith('http'):
                    found_images.add(url_key)
        except:
            pass

    # 统一过滤 + 去重 + 保留高清版本
    raw_list = list(found_images)
    image_urls = _filter_image_urls(raw_list)
    extracted["image_urls"] = image_urls[:50]

    # ===== 变体图片分组 =====
    variant_images = {}
    if platform == 'amazon':
        variant_images = _extract_amazon_variant_images(soup)
    elif platform == 'wildberries':
        variant_images = _extract_wildberries_variants(html, soup)

    # 如果提取到变体图片，存储分组结果
    if variant_images:
        extracted["variant_images"] = variant_images
        logger.info("提取到 %s 个变体图片组: %s", len(variant_images), list(variant_images.keys()))

    # ===== Amazon 专属：提取"关于该商品"和"商品描述" =====
    if platform == 'amazon':
        bullets_el = soup.select_one('#feature-bullets')
        if bullets_el:
            items = bullets_el.select('li span.a-list-item')
            bullet_texts = [item.get_text(strip=True) for item in items if item.get_text(strip=True)]
            if bullet_texts:
                extracted["about_item"] = '\n'.join(bullet_texts)

        desc_selectors = [
            '#productDescription',
            '#productDescription_feature_div',
            '.aplus-v2',
            '#aplus',
            '#aplus_feature_div',
            '.aplus-module-wrapper',
            'div[data-aplus-entity]',
        ]
        for selector in desc_selectors:
            desc_el = soup.select_one(selector)
            if desc_el:
                text = desc_el.get_text(strip=True)
                if text and len(text) > 50:
                    extracted["product_description"] = text[:5000]
                    break

        if not extracted["product_description"]:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        desc = data.get('description', '')
                        if desc:
                            extracted["product_description"] = desc[:5000]
                            break
                except:
                    pass

    return extracted


# ==================== 爬虫主入口 ====================

async def crawl_product(url: str) -> dict:
    """抓取商品页面信息"""
    html = await _fetch_html(url)
    return _extract_from_html(html, url)


# ==================== 第二层：决策层 (DeepSeek-V4) ====================

async def classify_images_deepseek(image_urls: list, product_name: str, platform: str) -> list:
    """使用 DeepSeek 对图片进行分类和重命名"""
    if not DEEPSEEK_API_KEY:
        logger.warning("未配置 DEEPSEEK_API_KEY，使用默认分类")
        return _default_classify(image_urls, product_name, platform)

    short_name = _sanitize_filename(product_name[:20]) if product_name else "product"
    ai_image_urls = [{"url": url} for url in image_urls]

    prompt = f"""你是一个电商产品图片分类专家。请对以下产品图片进行分类，并推荐文件名。

产品名称: {product_name}
平台: {platform}

分类规则：
- "main": 主图（产品正面/整体图，通常第一张）
- "sku": 变体图（不同颜色/尺寸的展示）
- "desc": 描述图（细节展示、尺寸说明等）

文件名格式: {platform}_{short_name}_NUM_type.jpg

要求：
- 每张图片返回一个分类结果
- type 只能为 "main" 或 "sku" 或 "desc"
- new_name 格式: {platform}_{short_name}_NUM_type.jpg，其中NUM为两位数字序号

图片列表:
{json.dumps(ai_image_urls, indent=2)}

只返回JSON数组，不要其他文字说明。"""

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个电商产品图片分类专家，只返回JSON格式结果。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4096
    }

    try:
        proxy_url = _get_proxy_server()
        async with aiohttp.ClientSession(proxy=proxy_url) as session:
            async with session.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=120) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("DeepSeek API 错误 (%s): %s", resp.status, text)
                    return _default_classify(image_urls, product_name, platform)

                data = await resp.json()
                content = data["choices"][0]["message"]["content"]

                # 清理响应内容，提取JSON
                content = content.strip()
                if content.startswith("```"):
                    content = re.sub(r'^```(?:json)?\s*', '', content)
                    content = re.sub(r'\s*```$', '', content)

                result = json.loads(content)
                if isinstance(result, list):
                    return result
                return _default_classify(image_urls, product_name, platform)

    except Exception as e:
        logger.error("DeepSeek 调用失败: %s", e)
        return _default_classify(image_urls, product_name, platform)


def _default_classify(image_urls: list, product_name: str, platform: str) -> list:
    """默认分类逻辑（无AI时的降级方案）"""
    short_name = _sanitize_filename(product_name[:20]) if product_name else "product"
    result = []

    for i, url in enumerate(image_urls):
        if i == 0:
            img_type = "main"
        elif i < 4:
            img_type = "sku"
        else:
            img_type = "desc"

        new_name = f"{platform}_{short_name}_{i+1:02d}_{img_type}.jpg"
        result.append({
            "url": url,
            "type": img_type,
            "new_name": new_name
        })

    return result


# ==================== 第三层：执行层 (异步下载 + Pillow 转 JPG) ====================

async def download_image(semaphore: asyncio.Semaphore, session: aiohttp.ClientSession,
                         url: str, save_path: str, index: int, total: int) -> dict:
    """下载单张图片并转换为JPG"""
    async with semaphore:
        try:
            logger.info("  [%s/%s] 下载中: %s...", index, total, url[:60])
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return {"url": url, "success": False, "error": f"HTTP {resp.status}"}

                content_type = resp.headers.get("Content-Type", "")
                if "image" not in content_type:
                    return {"url": url, "success": False, "error": f"非图片类型: {content_type}"}

                raw_data = await resp.read()

                # 使用 Pillow 转换为 JPG
                try:
                    img = Image.open(io.BytesIO(raw_data))
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')

                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    img.save(save_path, 'JPEG', quality=85)

                    file_size = os.path.getsize(save_path)
                    logger.info("  [%s/%s] OK 已保存: %s (%.1fKB)", index, total, os.path.basename(save_path), file_size / 1024)

                    return {
                        "url": url,
                        "success": True,
                        "local": os.path.relpath(save_path, DATA_ROOT),
                        "size": file_size
                    }

                except Exception as e:
                    return {"url": url, "success": False, "error": f"图片转换失败: {str(e)}"}

        except Exception as e:
            return {"url": url, "success": False, "error": str(e)}


async def download_images(classified_images: list, save_dir: str) -> list:
    """
    异步并发下载图片并转换为JPG
    返回: [{url, local, type, success, error}]
    """
    os.makedirs(save_dir, exist_ok=True)

    semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)
    connector = aiohttp.TCPConnector(limit=CONCURRENT_DOWNLOADS + 5)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    proxy_url = _get_proxy_server()

    results = []
    async with aiohttp.ClientSession(connector=connector, headers=headers, proxy=proxy_url) as session:
        tasks = []
        for i, item in enumerate(classified_images):
            save_path = os.path.join(save_dir, item["new_name"])
            task = download_image(semaphore, session, item["url"], save_path, i + 1, len(classified_images))
            tasks.append(task)

        download_results = await asyncio.gather(*tasks)

        for i, item in enumerate(classified_images):
            dr = download_results[i]
            results.append({
                "url": item["url"],
                "type": item["type"],
                "new_name": item["new_name"],
                "local": dr.get("local", ""),
                "success": dr.get("success", False),
                "error": dr.get("error", "")
            })

    return results


# ==================== 主流程 ====================

async def run_collect_pipeline(url: str, task_id: str, status_callback=None) -> dict:
    """
    执行完整的采集流水线
    1. Crawl4AI 抓取
    2. DeepSeek 分类
    3. 异步下载 + 转JPG
    4. 保存数据
    """
    def update_status(status, progress=0, message=""):
        if status_callback:
            status_callback(task_id, status, progress, message)

    try:
        # 阶段1: 抓取
        update_status("crawling", 10, "正在抓取商品页面...")
        logger.info("[%s] 开始抓取: %s", task_id, url)
        product_data = await crawl_product(url)
        logger.info("[%s] 抓取完成: 标题=%s, 图片数=%s", task_id, product_data['title'][:30], len(product_data['image_urls']))

        if not product_data["image_urls"]:
            raise Exception("未找到任何产品图片")

        update_status("classifying", 40, f"已抓取 {len(product_data['image_urls'])} 张图片，正在AI分类...")

        # 阶段2: DeepSeek 分类
        product_name = product_data["title"] or "product"
        classified = await classify_images_deepseek(
            product_data["image_urls"],
            product_name,
            product_data["platform"]
        )
        logger.info("[%s] 分类完成: %s 张图片已分类", task_id, len(classified))

        update_status("downloading", 60, f"正在下载并转换图片 (共{len(classified)}张)...")

        # 阶段3: 下载
        collect_dir = _get_collect_dir(task_id)
        images_dir = os.path.join(collect_dir, "images")

        download_results = await download_images(classified, images_dir)

        success_count = sum(1 for r in download_results if r["success"])
        fail_count = sum(1 for r in download_results if not r["success"])

        update_status("saving", 90, f"下载完成 ({success_count}成功/{fail_count}失败)，正在保存数据...")

        # 阶段4: 保存数据
        os.makedirs(collect_dir, exist_ok=True)

        product_data_path = os.path.join(collect_dir, "product_data.json")
        product_data["collected_at"] = datetime.now().isoformat()
        with open(product_data_path, "w", encoding="utf-8") as f:
            json.dump(product_data, f, ensure_ascii=False, indent=2)

        mapping_path = os.path.join(collect_dir, "images_mapping.json")
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(download_results, f, ensure_ascii=False, indent=2)

        update_status("completed", 100, f"采集完成！{success_count}张图片已下载")

        return {
            "task_id": task_id,
            "status": "completed",
            "url": url,
            "platform": product_data["platform"],
            "title": product_data["title"],
            "price": product_data.get("price", ""),
            "image_count": len(product_data["image_urls"]),
            "downloaded": success_count,
            "failed": fail_count,
            "data_dir": collect_dir,
            "product_data": product_data_path,
            "images_mapping": mapping_path,
            "images_dir": images_dir
        }

    except Exception as e:
        error_msg = str(e)
        logger.error("[%s] 采集失败: %s", task_id, error_msg)
        update_status("error", 0, f"采集失败: {error_msg}")

        return {
            "task_id": task_id,
            "status": "error",
            "url": url,
            "error": error_msg
        }
