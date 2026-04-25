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
import aiohttp
import aiofiles
from datetime import datetime
from urllib.parse import urlparse
from PIL import Image
import io

# ---------- 配置 ----------
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
CONCURRENT_DOWNLOADS = 5  # 并发下载数
DATA_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

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


# ==================== 第一层：抓取层 (Playwright + requests 双引擎) ====================

import requests as sync_requests

def _fetch_html_requests(url: str) -> str:
    """使用 requests 获取页面 HTML（快速模式）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    resp = sync_requests.get(url, headers=headers, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def _fetch_html_playwright(url: str) -> str:
    """使用 Playwright 获取页面 HTML（支持 JS 渲染）"""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            page = await context.new_page()
            
            # 设置超时
            page.set_default_timeout(25000)
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 等待页面加载完成（简短等待）
                await page.wait_for_timeout(5000)  # 等待5秒让JS执行
            except Exception as e:
                print(f"Playwright 页面加载超时，继续处理已有内容: {e}")
                await page.wait_for_timeout(3000)
            
            html = await page.content()
            await browser.close()
            return html
    except Exception as e:
        raise Exception(f"Playwright 抓取失败: {str(e)}")


async def _fetch_html(url: str) -> str:
    """智能获取页面 HTML：Amazon 等动态页面用 Playwright，其他用 requests"""
    platform = _extract_platform(url)
    # 需要 JS 渲染的平台
    js_platforms = ['amazon', 'ozon', 'wildberries']
    
    if platform in js_platforms:
        print(f"使用 Playwright 抓取 (平台: {platform})")
        return await _fetch_html_playwright(url)
    
    try:
        return _fetch_html_requests(url)
    except Exception as e:
        print(f"Requests 抓取失败，尝试 Playwright: {e}")
        return await _fetch_html_playwright(url)


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
        "about_item": "",           # 关于该商品（Amazon feature bullet points）
        "product_description": "",  # 商品描述（Amazon 产品详情）
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
    
    # ===== 图片提取（增强版） =====
    found_images = set()
    
    # 1. 从 JSON-LD 结构化数据中提取
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                # 提取 image 字段
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
    
    # 3. 从 Amazon 特定选择器提取
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
                    if src and 'icon' not in src.lower():
                        if src.startswith('//'):
                            src = 'https:' + src
                        found_images.add(src)
                        break
        except:
            pass
    
    # 4. 从所有 img 标签提取（过滤小图标）
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-old-hires') or ''
        if not src:
            continue
        if any(x in src.lower() for x in ['icon', 'avatar', 'logo', 'spacer', 'pixel', '1x1', 'flag', 'badge']):
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
    
    # 6. 从 data 属性中提取图片 URL
    for tag in soup.find_all(attrs={"data-a-dynamic-image": True}):
        try:
            dynamic_data = json.loads(tag["data-a-dynamic-image"])
            for url_key in dynamic_data.keys():
                if url_key.startswith('http'):
                    found_images.add(url_key)
        except:
            pass
    
    # 过滤：只保留包含图片扩展名或图片路径的URL
    filtered = []
    for src in found_images:
        src_lower = src.lower()
        # 优先保留包含图片扩展名的
        if any(ext in src_lower for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
            filtered.append(src)
        # 其次保留包含图片路径关键词的
        elif any(kw in src_lower for kw in ['images', 'media', 'img', 'photo', 'picture']):
            filtered.append(src)
    
    # 去重并限制数量
    extracted["image_urls"] = list(dict.fromkeys(filtered))[:50]
    
    # ===== Amazon 专属：提取"关于该商品"和"商品描述" =====
    if platform == 'amazon':
        # 提取 "关于该商品"（feature bullet points）
        bullets_el = soup.select_one('#feature-bullets')
        if bullets_el:
            items = bullets_el.select('li span.a-list-item')
            bullet_texts = [item.get_text(strip=True) for item in items if item.get_text(strip=True)]
            if bullet_texts:
                extracted["about_item"] = '\n'.join(bullet_texts)
        
        # 提取 "商品描述"（产品详情描述）
        # 尝试多个可能的 Amazon 描述区域
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
                    extracted["product_description"] = text[:5000]  # 限制长度
                    break
        
        # 如果上面没找到，尝试从 JSON-LD 中提取 description
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


async def crawl_product(url: str) -> dict:
    """
    使用 requests/Playwright + BeautifulSoup 抓取商品页面
    返回结构化数据
    """
    try:
        html = await _fetch_html(url)
        extracted = _extract_from_html(html, url)
        return extracted
    except Exception as e:
        raise Exception(f"抓取失败: {str(e)}")


# ==================== 第二层：决策层 (DeepSeek-V4) ====================

async def classify_images_deepseek(image_urls: list, product_name: str, platform: str) -> list:
    """
    调用 DeepSeek API 对图片进行分类和重命名
    返回: [{url, type, new_name}]
    """
    if not DEEPSEEK_API_KEY:
        # 如果没有 API Key，使用默认命名规则
        return _default_classify(image_urls, product_name, platform)
    
    # 限制发送给 AI 的图片数量（太多会导致超时）
    ai_image_urls = image_urls[:20]
    short_name = _sanitize_filename(product_name[:20]) if product_name else "product"
    
    prompt = f"""你是一个电商产品图片分类专家。请分析以下产品图片URL列表，对每张图片进行分类并给出推荐文件名。

产品名称: {product_name}
平台: {platform}

图片分类规则:
- main: 产品主图（首图、展示图）
- sku: SKU/变体图（不同颜色、角度、尺寸展示）
- desc: 详情描述图（功能说明、细节展示、场景图）

请返回严格的JSON数组格式（不要markdown代码块标记），每个元素包含:
- "url": 原图URL
- "type": "main" 或 "sku" 或 "desc"
- "new_name": 推荐文件名（格式: {platform}_{short_name}_NUM_{type}.jpg，其中NUM为两位数字序号）

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
        async with aiohttp.ClientSession() as session:
            async with session.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=120) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"DeepSeek API 错误 ({resp.status}): {text}")
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
        print(f"DeepSeek 调用失败: {e}")
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
            print(f"  [{index}/{total}] 下载中: {url[:60]}...")
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
                    # 转换 RGBA/P 到 RGB
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # 保存为 JPG
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    img.save(save_path, 'JPEG', quality=85)
                    
                    file_size = os.path.getsize(save_path)
                    print(f"  [{index}/{total}] OK 已保存: {os.path.basename(save_path)} ({file_size/1024:.1f}KB)")
                    
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
    
    results = []
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
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
        print(f"[{task_id}] 开始抓取: {url}")
        product_data = await crawl_product(url)
        print(f"[{task_id}] 抓取完成: 标题={product_data['title'][:30]}, 图片数={len(product_data['image_urls'])}")
        
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
        print(f"[{task_id}] 分类完成: {len(classified)} 张图片已分类")
        
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
        
        # 保存 product_data.json
        product_data_path = os.path.join(collect_dir, "product_data.json")
        product_data["collected_at"] = datetime.now().isoformat()
        with open(product_data_path, "w", encoding="utf-8") as f:
            json.dump(product_data, f, ensure_ascii=False, indent=2)
        
        # 保存 images_mapping.json
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
        print(f"[{task_id}] 采集失败: {error_msg}")
        update_status("error", 0, f"采集失败: {error_msg}")
        
        return {
            "task_id": task_id,
            "status": "error",
            "url": url,
            "error": error_msg
        }
