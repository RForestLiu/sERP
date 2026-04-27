import json

with open('data/ozon_cache/ozon_anling_category_tree.json', 'r', encoding='utf-8') as f:
    tree = json.load(f)

def _node_id(node):
    return node.get('type_id') or node.get('description_category_id') or node.get('id')

def _node_name(node):
    return node.get('type_name') or node.get('category_name') or node.get('name', '')

def count_nodes(nodes):
    """递归统计节点总数"""
    total = 0
    for node in nodes:
        total += 1
        children = node.get('children', [])
        if children:
            total += count_nodes(children)
    return total

grand_total = 0
with open('一级分类统计.txt', 'w', encoding='utf-8') as f:
    for i, node in enumerate(tree, 1):
        nid = _node_id(node)
        nname = _node_name(node)
        children = node.get('children', [])
        
        # 统计该一级分类下的所有节点（包括自身）
        sub_count = count_nodes([node])
        grand_total += sub_count
        
        direct_children = len(children)
        leaf_nodes = count_nodes(children)  # 子节点总数（不含自身）
        
        f.write(f"{i}. [{nid}] {nname}\n")
        f.write(f"   直接子分类: {direct_children} 个\n")
        f.write(f"   子节点总数: {leaf_nodes} 个\n")
        f.write(f"   该分类总计(含自身): {sub_count} 个\n\n")
    
    f.write(f"=== 汇总 ===\n")
    f.write(f"一级分类数: {len(tree)}\n")
    f.write(f"全树节点总数: {grand_total}\n")

print("已生成 一级分类统计.txt")
