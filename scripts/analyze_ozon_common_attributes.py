"""
查询多个 Ozon 产品类目属性，归纳公共属性。
Tree structure: top-level → mid-level (with description_category_id) → type (with type_id)
"""
import json, os, re, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv()
from src.serp.listing.infrastructure.ozon_api import OzonApiClient

STORE_ID = "ozon_anling"
DATA_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

with open(os.path.join(DATA_ROOT, "stores.json"), "r") as f:
    stores_data = json.load(f)
store_list = stores_data if isinstance(stores_data, list) else stores_data.get("stores", [])
store = next((s for s in store_list if s.get("id") == STORE_ID), None)

def _resolve_env(value: str) -> str:
    if not value: return ""
    return re.sub(r'\$\{([^}]+)\}', lambda m: os.environ.get(m.group(1), m.group(0)), value)

client = OzonApiClient(lambda sid: (
    _resolve_env(str(store.get("client_id", ""))),
    _resolve_env(str(store.get("api_key", "")))
))

# Step 1: Parse category tree
print("=" * 60)
print("Step 1: Parsing category tree structure...")
print("=" * 60)

tree_data, err = client.call(STORE_ID, "/v1/description-category/tree", {"language": "DEFAULT"})
if err: print(f"ERROR: {err}"); sys.exit(1)

result = tree_data.get("result", tree_data)
tree = result.get("category_tree", [result]) if isinstance(result, dict) else result

# Structure: top-level → mid-level (has description_category_id + children of types) → type (has type_id)
# Top-level nodes have: description_category_id, category_name, children
# Mid-level nodes have: description_category_id, category_name, children (each child is a type)
# Type nodes have: type_name, type_id, children (empty)

mid_level_categories = []  # Categories at mid-level (with types)

for top_node in tree:
    top_name = top_node.get("category_name", "")
    for mid_node in top_node.get("children", []):
        mid_cid = mid_node.get("description_category_id", 0)
        mid_name = mid_node.get("category_name", "")
        types = mid_node.get("children", [])

        if mid_cid and mid_name and types:
            # Get first type_id
            first_type = types[0]
            type_id = first_type.get("type_id", 0)
            type_name = first_type.get("type_name", "")

            mid_level_categories.append({
                "id": mid_cid,
                "name": mid_name,
                "type_id": type_id,
                "type_name": type_name,
                "type_count": len(types),
                "top_parent": top_name,
                "path": f"{top_name} > {mid_name} > {type_name}",
            })

print(f"Found {len(mid_level_categories)} mid-level categories with types")

# Group by top-level parent for diversity
by_parent = defaultdict(list)
for c in mid_level_categories:
    by_parent[c["top_parent"]].append(c)

# Select diverse categories from different top-level branches
selected = []
for parent, cats in sorted(by_parent.items()):
    if cats:
        selected.append(cats[0])  # First type from each branch
    if len(selected) >= 12:
        break

print(f"Selected {len(selected)} categories from different branches:")
for c in selected:
    print(f"  [{c['id']}] {c['name'][:45]} (type_id={c['type_id']}) — {c['top_parent'][:30]}")

# Step 2: Query attributes
print("\n" + "=" * 60)
print("Step 2: Fetching attributes...")
print("=" * 60)

all_attributes = {}
successful = []
failed = []

for cat in selected:
    cid = cat["id"]
    tid = cat["type_id"]
    print(f"  [{cid}] {cat['name'][:40]} (type_id={tid})...", end=" ", flush=True)

    payload = {
        "description_category_id": cid,
        "type_id": tid,
        "language": "DEFAULT",
    }
    data, err = client.call(STORE_ID, "/v1/description-category/attribute", payload)

    if err:
        print(f"ERROR: {err[:100]}")
        failed.append(cat)
        continue

    attrs = data.get("result", [])
    print(f"{len(attrs)} attrs")

    attr_map = {}
    for a in attrs:
        aid = a.get("id", 0)
        attr_map[aid] = {
            "id": aid, "name": a.get("name", ""),
            "description": a.get("description", ""),
            "type": a.get("type", ""),
            "is_required": a.get("is_required", False),
            "is_collection": a.get("is_collection", False),
            "category_dependent": a.get("category_dependent", False),
            "dictionary_id": a.get("dictionary_id", 0),
        }
    all_attributes[cid] = attr_map
    successful.append(cat)

total_cats = len(successful)
print(f"\nSuccess: {total_cats}, Failed: {len(failed)}")

if total_cats < 2:
    print("Not enough data. Exiting.")
    sys.exit(0)

# Step 3: Cross-category analysis
print("\n" + "=" * 60)
print(f"Step 3: Cross-category analysis ({total_cats} categories)")
print("=" * 60)

# Build attr_id → categories map
attr_categories = {}
attr_details = {}  # attr_id → best info (from any category)
for cid, attrs in all_attributes.items():
    cat_info = next((c for c in successful if c["id"] == cid), {"name": str(cid), "path": ""})
    for aid, ainfo in attrs.items():
        if aid not in attr_categories:
            attr_categories[aid] = []
            attr_details[aid] = ainfo
        attr_categories[aid].append({
            "cat_id": cid, "cat_name": cat_info["name"],
            "cat_path": cat_info.get("path", ""),
        })

sorted_attrs = sorted(attr_categories.items(), key=lambda x: len(x[1]), reverse=True)

common_all = []; common_most = []; common_some = []; common_few = []

for aid, entries in sorted_attrs:
    count = len(entries)
    info = attr_details[aid]
    entry_data = {
        "attribute_id": aid, "name_ru": info["name"],
        "description": info["description"], "type": info["type"],
        "is_required": info["is_required"],
        "category_dependent": info["category_dependent"],
        "dictionary_id": info["dictionary_id"],
        "occurrence_count": count,
        "occurrence_pct": round(count / total_cats * 100, 1),
        "categories": [{"id": e["cat_id"], "name": e["cat_name"]} for e in entries],
    }

    if count == total_cats: common_all.append(entry_data)
    elif count >= total_cats * 0.6: common_most.append(entry_data)
    elif count >= 2: common_some.append(entry_data)
    else: common_few.append(entry_data)

print(f"  Universal (all {total_cats}):  {len(common_all)}")
print(f"  Most     (>=60%):              {len(common_most)}")
print(f"  Some     (2+):                 {len(common_some)}")
print(f"  Specific (1 only):             {len(common_few)}")

# Detailed output
print(f"\n{'='*60}")
print(f"UNIVERSAL ATTRIBUTES (present in ALL {total_cats} categories)")
print(f"{'='*60}")
for a in common_all:
    req = "必填" if a["is_required"] else "可选"
    dep = "类目依赖" if a["category_dependent"] else "独立"
    print(f"  [{a['attribute_id']}] {a['name_ru']}")
    print(f"      Type: {a['type']} | {req} | {dep} | dict_id={a['dictionary_id']}")
    if a["description"]:
        print(f"      Desc: {a['description'][:150]}")

print(f"\n{'='*60}")
print(f"MOST COMMON (>=60% of {total_cats} categories)")
print(f"{'='*60}")
for a in common_most:
    req = "必填" if a["is_required"] else "可选"
    cat_names = ", ".join(e["name"] for e in a["categories"])
    print(f"  [{a['attribute_id']}] {a['name_ru']} — {a['type']} | {req} | {a['occurrence_count']}/{total_cats}")
    print(f"      In: {cat_names}")

# Step 4: Categorize and enrich public attributes with Chinese names
print(f"\n{'='*60}")
print("Step 4: Enriching with Chinese names and categories...")
print("=" * 60)

# Known attribute name translations (from wallet work + general knowledge)
NAME_CN_MAP = {
    "Бренд": "品牌",
    "Тип": "产品类型",
    "Название": "产品名称",
    "Описание": "产品描述",
    "Цена": "价格",
    "Валюта": "货币",
    "Артикул": "货号/Artikel",
    "Штрихкод": "条形码",
    "Вес": "重量",
    "Ширина": "宽度",
    "Высота": "高度",
    "Длина": "深度/长度",
    "Цвет": "颜色",
    "Размер": "尺寸",
    "Материал": "材质/材料",
    "Страна-производитель": "生产国",
    "Гарантия": "质保",
    "Комплектация": "配件/包装内容",
    "Пол": "性别/适用性别",
    "Возраст": "年龄段",
    "Назначение": "用途/适用场景",
    "Коллекция": "系列/Collection",
    "Сезон": "季节",
    "Состав": "成分",
    "Упаковка": "包装",
    "Количество": "数量",
    "Объем": "容量/体积",
    "Форма": "形状",
    "Стиль": "风格",
    "Застежка": "闭合方式",
    "Карманы": "口袋数量",
    "Отделения": "隔层数",
    "Ручки": "提手类型",
    "Ремешок": "肩带类型",
    "Подкладка": "内衬材质",
    "Фурнитура": "五金件材质",
    "Узор": "图案/花纹",
    "Вид спорта": "运动类型",
    "Питание": "供电方式",
    "Экран": "屏幕",
    "Память": "内存",
    "Камера": "摄像头",
    "Процессор": "处理器",
    "Батарея": "电池",
    "Влагозащита": "防水等级",
    "Беспроводные": "无线技术",
    "Интерфейсы": "接口",
    "Комплект": "套装内容",
    "Запах": "香型",
    "Объем/вес": "容量/净重",
    "Тип кожи": "适用肤质",
    "Солнцезащита": "防晒系数",
    "Эффект": "功效",
    "Активный": "活性成分",
    "Время работы": "续航时间",
    "Совместимость": "兼容性",
    "Материал корпуса": "表壳材质",
    "Материал ремешка": "表带材质",
    "Механизм": "机芯类型",
    "Водонепроницаемость": "防水深度",
    "Стекло": "表镜材质",
    "Вес товара": "商品重量",
    "Габариты": "商品尺寸",
    "Размеры упаковки": "包装尺寸",
    "Срок годности": "保质期",
    "Условия хранения": "储存条件",
    "Температура": "温度",
    "Мощность": "功率",
    "Напряжение": "电压",
}

# Classify attributes by their functional category
def classify_attribute(name_ru, description, attr_type):
    """Classify attribute into functional category."""
    name_lower = (name_ru + " " + description).lower()

    CLASSIFICATION = {
        "基本信息": ["название", "тип", "вид", "категория", "модель", "артикул", "описание", "аннотация"],
        "品牌与标识": ["бренд", "торговая марка", "производитель", "страна", "логотип", "коллекция"],
        "价格与货币": ["цена", "валюта", "стоимость", "скидка"],
        "媒体资源": ["изображение", "фото", "картинка", "видео", "pdf", "rich-контент", "медиа", "360",
                     "инфографика", "презентация", "ракурс", "скриншот"],
        "条码与编码": ["штрихкод", "ean", "upc", "isbn", "код", "идентификатор", "gtin", "barcode",
                     "яндекс", "складской", "сим", "серийный", "imei"],
        "物理属性": ["вес", "размер", "габарит", "длина", "ширина", "высота", "глубина", "объем",
                    "диаметр", "толщина", "форма", "площадь"],
        "材质与成分": ["материал", "состав", "ткань", "кожа", "металл", "пластик", "стекло", "дерево",
                     "подкладка", "фурнитура", "наполнитель", "покрытие"],
        "颜色与外观": ["цвет", "оттенок", "окрас", "расцветка", "узор", "принт", "рисунок", "украшение",
                     "дизайн", "стиль", "фактура", "поверхность", "покрытие"],
        "适用信息": ["пол", "возраст", "назначение", "сезон", "аудитория", "спорт", "активность",
                   "праздник", "событие", "повод", "применение", "использование"],
        "包装与配件": ["упаковк", "комплект", "коробка", "пакет", "чехол", "вставка", "вкладыш",
                     "инструкция", "гарантия", "сертификат", "документация"],
        "技术规格": ["процессор", "память", "батарея", "аккумулятор", "экран", "дисплей", "камера",
                   "разрешение", "частота", "мощность", "напряжение", "интерфейс", "порт",
                   "беспровод", "bluetooth", "wifi", "связь", "сеть", "датчик", "сенсор"],
        "物流信息": ["доставка", "склад", "отгрузка", "транспортировка", "хранение", "температура"],
        "法规与合规": ["сертификат", "декларация", "стандарт", "соответствие", "разрешение",
                     "лицензия", "патент", "еас", "ростест", "честный знак"],
        "营销信息": ["ключевые слова", "теги", "хэштег", "метка", "ярлык", "продвижение",
                   "реклама", "акция", "скидка", "распродажа", "новинка", "хит", "бестселлер",
                   "seo", "поиск"],
    }

    for category, keywords in CLASSIFICATION.items():
        for kw in keywords:
            if kw in name_lower:
                return category
    return "其他"

# Enrich common attributes
for group in [common_all, common_most, common_some]:
    for a in group:
        a["name_cn"] = NAME_CN_MAP.get(a["name_ru"], "")
        a["functional_category"] = classify_attribute(a["name_ru"], a["description"], a["type"])

# Print enriched universal attributes
print("\nUniversal attributes with Chinese names:")
for a in common_all:
    cn = a.get("name_cn", "") or "?"
    cat = a.get("functional_category", "?")
    print(f"  [{a['attribute_id']}] {a['name_ru']} ({cn}) — {cat}")

# Save
output = {
    "meta": {
        "description": "Ozon 跨类目公共属性分析",
        "total_categories_queried": total_cats,
        "categories": [{"id": c["id"], "name": c["name"], "type_id": c["type_id"],
                        "type_name": c.get("type_name", ""), "path": c.get("path", "")}
                       for c in successful],
        "generated_at": datetime.now().isoformat(),
    },
    "summary": {
        "universal": len(common_all), "most_categories": len(common_most),
        "some_categories": len(common_some), "category_specific": len(common_few),
        "total_unique_attributes": len(attr_categories),
    },
    "common_attributes": {
        "universal": common_all, "most_categories": common_most,
        "some_categories": common_some, "category_specific": common_few,
    },
}

out_path = os.path.join(DATA_ROOT, "knowledge", "ozon", "common_attributes.json")
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\nSaved: {out_path}")
print(f"Size: {os.path.getsize(out_path)} bytes")
print("Done!")
