import json

with open('data/ozon_cache/ozon_anling_category_tree.json', 'r', encoding='utf-8') as f:
    tree = json.load(f)

def _node_id(node):
    return node.get('type_id') or node.get('description_category_id') or node.get('id')

def _node_name(node):
    return node.get('type_name') or node.get('category_name') or node.get('name', '')

# 计数器
counter = [0]

def gen_tree_lines(nodes, prefix="", depth=0):
    """生成紧凑树文本（带层级序号）"""
    lines = []
    for node in nodes:
        node_id = _node_id(node)
        node_name = _node_name(node)
        counter[0] += 1
        idx = counter[0]
        
        # 用缩进和序号表示层级
        indent = "   " * depth
        line = f"{indent}{prefix}{idx}. [{node_id}] {node_name}"
        lines.append(line)
        
        children = node.get('children', [])
        if children:
            child_lines = gen_tree_lines(children, f"{prefix}{idx}.", depth + 1)
            lines.extend(child_lines)
    
    return lines

lines = gen_tree_lines(tree)
print(f"总节点数: {counter[0]}")
print(f"紧凑树行数: {len(lines)}")

# 计算字符数
tree_text = "\n".join(lines)
print(f"紧凑树字符数: {len(tree_text)}")

# 写入 txt
with open('品类翻译_待翻译内容.txt', 'w', encoding='utf-8') as f:
    f.write("""# 翻译任务：Ozon 俄语品类树 → 中文翻译

## 任务说明
将以下 Ozon 电商平台的俄语品类树逐行翻译成中文。

## 核心规则（非常重要）
1. **保持完全相同的树结构**：不改变任何行的缩进、序号编号、节点的排列顺序
2. **保持每个节点的中括号 [ID]**：ID 是数字，绝不能修改或丢失
3. **追加中文翻译**：在每个节点原有的俄语名**后面**，用一对半角括号 `(中文翻译)` 追加中文
4. **不要删除俄语原文**：格式是 `俄语名(中文名)`，俄语原文必须保留
5. **只修改俄语名部分**：在俄语名末尾添加 (中文翻译)，不要改动序号、缩进、ID

## 翻译要求
- 准确传达原意，使用电商行业通用术语
- 对于品牌词（如 Apple, Samsung, Nike）、专有名词、型号名保留原文
- 如果某个品类名包含多个词，尽量用中文电商术语简洁表达

## 示例

### 输入
```
1. [17027488] Телефоны
   1.1 [17027489] Смартфоны
      1.1.1 [95400] Смартфоны Apple
      1.1.2 [95399] Смартфоны Samsung
      1.1.3 [78284142] Смартфоны Xiaomi
   1.2 [17028678] Аксессуары для телефонов
      1.2.1 [971739850] Чехлы
      1.2.2 [971046367] Защитные стекла
      1.2.3 [971014516] Держатели и подставки
   1.3 [17027490] Наушники
      1.3.1 [97100] Проводные наушники
      1.3.2 [97042] Беспроводные наушники
         1.3.2.1 [97043] Bluetooth-наушники
         1.3.2.2 [97044] Наушники с шумоподавлением
```

### 正确输出
```
1. [17027488] Телефоны(手机)
   1.1 [17027489] Смартфоны(智能手机)
      1.1.1 [95400] Смартфоны Apple(苹果智能手机)
      1.1.2 [95399] Смартфоны Samsung(三星智能手机)
      1.1.3 [78284142] Смартфоны Xiaomi(小米智能手机)
   1.2 [17028678] Аксессуары для телефонов(手机配件)
      1.2.1 [971739850] Чехлы(手机壳)
      1.2.2 [971046367] Защитные стекла(钢化膜)
      1.2.3 [971014516] Держатели и подставки(手机支架)
   1.3 [17027490] Наушники(耳机)
      1.3.1 [97100] Проводные наушники(有线耳机)
      1.3.2 [97042] Беспроводные наушники(无线耳机)
         1.3.2.1 [97043] Bluetooth-наушники(蓝牙耳机)
         1.3.2.2 [97044] Наушники с шумоподавлением(降噪耳机)
```

### 错误示范（请不要这样做）
```
- ❌ 删除了俄语原文：1. [17027488] 手机
- ❌ 改了缩进/序号：   1. [17027489] Смартфоны(智能手机)
- ❌ 改了 ID：1. [11111] Смартфоны(智能手机)
- ❌ 中文放到了括号外：1. [17027489] (智能手机)Смартфоны
```

---

## 待翻译的 Ozon 品类树

""")
    
    # 品类内容 - 紧凑树格式
    for line in lines:
        f.write(line + "\n")

print("文件已写入: 品类翻译_待翻译内容.txt")
