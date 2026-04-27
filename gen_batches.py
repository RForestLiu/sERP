"""
按一级大类生成翻译批次文件，每个大类一个独立文件，附带翻译背景上下文
"""
import json
import os
import re

with open('data/ozon_cache/ozon_anling_category_tree.json', 'r', encoding='utf-8') as f:
    tree = json.load(f)

def _node_id(node):
    return node.get('type_id') or node.get('description_category_id') or node.get('id')

def _node_name(node):
    return node.get('type_name') or node.get('category_name') or node.get('name', '')

# 将每个一级分类的所有节点展平为带 level 的条目
def flatten_tree(nodes, parent_level=""):
    """DFS 遍历，返回 level 列表"""
    entries = []
    for idx, node in enumerate(nodes, start=1):
        node_id = _node_id(node)
        node_name = _node_name(node)
        level = f"{parent_level}.{idx}" if parent_level else str(idx)
        entries.append({
            "id": str(node_id),
            "level": level,
            "ru": node_name
        })
        children = node.get('children', [])
        if children:
            entries.extend(flatten_tree(children, level))
    return entries

# 为每个一级分类生成翻译上下文
TOP_CATEGORY_CONTEXT = {
    0: "Товары для животных — 宠物用品（猫狗粮、宠物玩具、笼具、宠物护理等）",
    1: "Хобби и творчество — 手工艺与创意（DIY工具、针织、绘画、模型制作等）",
    2: "Одежда — 服装（男装、女装、童装、内衣、袜类等）",
    3: "Товары для курения и аксессуары — 吸烟用品及配件",
    4: "Детские товары — 童婴用品（玩具、童车、安全座椅、哺育用品等）",
    5: "Товары для взрослых — 成人用品",
    6: "Строительство и ремонт — 建材与装修（工具、五金、管件、电气、油漆等）",
    7: "Бытовая химия — 家用化学品（清洁剂、洗衣液、消毒剂等）",
    8: "Продукты питания — 食品饮料（零食、饮料、粮油、调味品等）",
    9: "Спорт и отдых — 运动与休闲（健身器材、户外装备、钓鱼、露营等）",
    10: "Фермерское хозяйство — 农用物资（种子、肥料、农具、畜牧用品等）",
    11: "Автотовары — 汽车用品（配件、机油、车载电子、清洗养护等）",
    12: "Антиквариат и коллекционирование — 古董与收藏品（钱币、邮票、艺术品等）",
    13: "Аптека — 药品与保健品（OTC药品、维生素、医疗器械等）",
    14: "Обувь — 鞋类（运动鞋、皮鞋、凉鞋、靴子等）",
    15: "Книги — 图书（纸质书、电子书等）",
    16: "Красота и гигиена — 美容个护（化妆品、洗发水、护肤品、香水等）",
    17: "Музыкальные инструменты — 乐器（吉他、钢琴、管乐、打击乐等）",
    18: "Дом и сад — 家居与花园（家具、灯具、装饰、园艺工具等）",
    19: "Канцелярские товары — 办公文具（笔、纸、办公设备等）",
    20: "Электроника — 电子产品（手机、电脑、耳机、智能穿戴、配件等）",
    21: "Кино, музыка, видеоигры, софт — 影音游戏与软件（光盘、游戏卡、软件等）",
    22: "Мебель — 家具（客厅家具、卧室家具、办公家具等）",
    23: "Галантерея и аксессуары — 服饰配件（箱包、皮带、眼镜、珠宝等）",
    24: "Бытовая техника — 家用电器（厨电、清洁电器、空调、洗衣机等）",
}

# 创建批次目录
batch_dir = "品类翻译_按大类"
os.makedirs(batch_dir, exist_ok=True)

total_all = 0

for idx, top_node in enumerate(tree, 1):
    nid = _node_id(top_node)
    nname = _node_name(top_node)
    # 安全文件名
    safe_name = re.sub(r'[\\/*?:"<>|]', '_', nname)[:20]
    
    # 展平该大类下的所有节点
    entries = flatten_tree([top_node])
    total_all += len(entries)
    
    # 找上下文
    context_line = TOP_CATEGORY_CONTEXT.get(idx-1, f"{nname}")
    
    filename = f"{batch_dir}/batch_{idx:02d}_{nid}_{safe_name}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"""# 翻译任务 - 大类 {idx}/25: {nname}

## 背景
Ozon 是俄罗斯最大的电商平台（类似亚马逊、京东）。
本批次是 Ozon 品类树中的一级分类 **"{nname}"** 及其所有子分类。
该大类的预期中文含义：{context_line}

请将以下俄语品类名称准确翻译成中文，使用中国电商行业通用术语。

## 规则
- 保持 ID 和 Level 字段不变
- 只翻译 RU 字段的内容（俄语→中文）
- 输出 JSON 格式必须与输入完全一致，但在 RU 内容后追加括号及中文
- 对于品牌词、专有名词（如 Apple, Samsung, Philips）保留原文不变
- 注意：品类名中可能包含品类特征描述（如颜色、材质等），需一并准确翻译
- 如果俄语词已有通用中文电商用语（如 "Красота" → "美容", "Авто" → "汽车"），使用该用语

## 示例

### 输入
[
  {{"id": "17027488", "level": "1", "ru": "Телефоны"}},
  {{"id": "17027489", "level": "1.1", "ru": "Смартфоны"}},
  {{"id": "95400", "level": "1.1.1", "ru": "Смартфоны Apple"}}
]

### 输出
[
  {{"id": "17027488", "level": "1", "ru": "Телефоны(手机)"}},
  {{"id": "17027489", "level": "1.1", "ru": "Смартфоны(智能手机)"}},
  {{"id": "95400", "level": "1.1.1", "ru": "Смартфоны Apple(苹果智能手机)"}}
]

---
## 待翻译数据（{len(entries)} 行，品类树层级：{nname} 及其所有子分类）

""")
        
        json_str = json.dumps(entries, ensure_ascii=False, indent=2)
        f.write(json_str)
        f.write("\n")
    
    print(f"  [{idx:02d}/25] {filename} ({len(entries)} 节点)")

print(f"\n全部完成！共 25 个批次文件（按大类），全树 {total_all} 节点，已保存到 '{batch_dir}/' 目录")
