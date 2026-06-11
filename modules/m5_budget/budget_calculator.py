"""M5: 预算与报价生成器
从 3D 模型精确计算工程量 → 自动报价
"""
import json, os, sys, math
from collections import OrderedDict
import ezdxf
from ezdxf.enums import TextEntityAlignment

# 单价库 (元/单位面积或元/项)
UNIT_PRICES = {
    "拆墙":          {"unit":"m2", "price": 45},
    "砌墙":          {"unit":"m2", "price": 85},
    "水电改造":      {"unit":"m2", "price": 180},
    "防水工程":      {"unit":"m2", "price": 65},
    "地砖铺贴":      {"unit":"m2", "price": 75},
    "墙砖铺贴":      {"unit":"m2", "price": 85},
    "木地板安装":    {"unit":"m2", "price": 45},
    "吊顶(平顶)":    {"unit":"m2", "price": 120},
    "吊顶(造型)":    {"unit":"m2", "price": 180},
    "墙面批灰油漆":  {"unit":"m2", "price": 35},
    "踢脚线":        {"unit":"m",  "price": 25},
    "窗台石":        {"unit":"m",  "price": 120},
    "门套安装":      {"unit":"套", "price": 350},
    "窗套安装":      {"unit":"套", "price": 250},
    "开关插座安装":  {"unit":"个", "price": 15},
    "灯具安装":      {"unit":"个", "price": 30},
    "保洁":          {"unit":"项", "price": 1500},
    "垃圾清运":      {"unit":"项", "price": 2000},
    "材料运输":      {"unit":"项", "price": 1500},
    "管理费":        {"unit":"项", "price": 0},
}

# 主材价格 (元/单位)
MATERIAL_PRICES = {
    "瓷砖800x800":   {"unit":"片", "price": 45, "m2_per_unit":0.64},
    "瓷砖300x600":   {"unit":"片", "price": 18, "m2_per_unit":0.18},
    "实木地板":      {"unit":"m2", "price": 280},
    "复合地板":      {"unit":"m2", "price": 120},
    "木纹砖":        {"unit":"m2", "price": 160},
    "防滑地砖":      {"unit":"m2", "price": 85},
    "乳胶漆":        {"unit":"桶", "price": 580, "m2_per_unit":40},
    "防水涂料":      {"unit":"桶", "price": 350, "m2_per_unit":8},
    "门槛石":        {"unit":"块", "price": 120},
}


def calculate_budget(conditions_json_path, dxf_output_path):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)

    space = conditions.get("space_data", {})
    style = conditions.get("style", {})
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")

    # ── 工程量计算 ──
    total_floor = 0
    total_wall = 0
    total_perimeter = 0
    room_count = 0

    for rm in space.get("rooms", []):
        w = rm["width_mm"] / 1000
        h = rm["height_mm"] / 1000
        total_floor += w * h
        total_perimeter += 2 * (w + h)
        room_count += 1

    total_wall = total_perimeter * 2.8  # 墙高 2.8m
    # 减去门窗面积估算
    door_area = 0.9 * 2.1 * 2  # 2个门
    window_area = (2.4*1.5 + 1.8*1.5 + 1.5*1.5 + 0.6*0.9)  # 所有窗
    total_wall -= (door_area + window_area)
    total_ceiling = total_floor  # 天花面积 ≈ 地面积

    # ── 报价计算 ──
    items = OrderedDict()

    # 1. 拆改
    items["拆改工程"] = [
        ("拆墙", max(5, total_wall * 0.05), UNIT_PRICES["拆墙"]),
        ("垃圾清运", 1, UNIT_PRICES["垃圾清运"]),
    ]

    # 2. 水电
    water_elect_area = 0
    for rm in space.get("rooms", []):
        wa = rm["width_mm"] * rm["height_mm"] / 1e6
        water_elect_area += wa
    items["水电工程"] = [
        ("水电改造", water_elect_area, UNIT_PRICES["水电改造"]),
        ("开关插座安装", 60, UNIT_PRICES["开关插座安装"]),
    ]

    # 3. 泥瓦
    tiles_floor = total_floor
    tiles_wall = total_wall * 0.3  # 约30%墙面贴砖(厨卫)
    items["泥瓦工程"] = [
        ("防水工程", 40, UNIT_PRICES["防水工程"]),
        ("地砖铺贴", tiles_floor, UNIT_PRICES["地砖铺贴"]),
        ("墙砖铺贴", tiles_wall, UNIT_PRICES["墙砖铺贴"]),
        ("门槛石", room_count, MATERIAL_PRICES["门槛石"]),
    ]

    # 4. 木工/吊顶
    ceiling_type = "吊顶(平顶)" if total_floor > 50 else "吊顶(造型)"
    items["木工/吊顶"] = [
        (ceiling_type, total_ceiling, UNIT_PRICES[ceiling_type]),
        ("门套安装", 3, UNIT_PRICES["门套安装"]),
        ("踢脚线", total_perimeter, UNIT_PRICES["踢脚线"]),
        ("窗台石", 4, UNIT_PRICES["窗台石"]),
    ]

    # 5. 油漆
    paint_area = total_wall + total_ceiling
    items["油漆工程"] = [
        ("墙面批灰油漆", paint_area, UNIT_PRICES["墙面批灰油漆"]),
    ]

    # 6. 主材（估算）
    floor_mat = style.get("floor_material", "复合地板")
    floor_price = MATERIAL_PRICES.get("复合地板")
    if "实木" in floor_mat: floor_price = MATERIAL_PRICES["实木地板"]
    elif "木纹" in floor_mat: floor_price = MATERIAL_PRICES["木纹砖"]
    elif "瓷砖" in floor_mat: floor_price = MATERIAL_PRICES["瓷砖800x800"]

    items["主材"] = [
        ("地面材料", total_floor, floor_price),
        ("墙面砖", tiles_wall, MATERIAL_PRICES["瓷砖300x600"]),
        ("乳胶漆", math.ceil(paint_area / 40), MATERIAL_PRICES["乳胶漆"]),
    ]

    # 7. 其他
    items["其他费用"] = [
        ("材料运输", 1, UNIT_PRICES["材料运输"]),
        ("保洁", 1, UNIT_PRICES["保洁"]),
        ("管理费", 1, {"unit":"项", "price": 0}),
    ]

    # ── 生成 DXF ──
    orig_dxf = os.path.join(base_dir, "原始结构底图.dxf")
    doc = ezdxf.readfile(orig_dxf) if os.path.exists(orig_dxf) else ezdxf.new("R2010")
    msp = doc.modelspace()

    for ln, c, lw in [("预算-项目", 6, 35), ("预算-金额", 2, 20), ("预算-合计", 1, 50), ("预算-说明", 8, 9)]:
        if ln not in [l.dxf.name for l in doc.layers]:
            doc.layers.add(ln, dxfattribs={"color": c, "lineweight": lw})

    y = 200
    msp.add_text("=== 预算报价书 ===", height=400,
                dxfattribs={"layer": "预算-说明"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 80

    project = conditions.get("project", {})
    msp.add_text("项目: %s   面积: %.1f m2" % (project.get("name","未命名"), total_floor),
                height=250, dxfattribs={"layer": "预算-说明"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 60

    grand_total = 0
    # 表头
    msp.add_text("%-20s %-12s %-10s %-12s %-12s" % ("项目", "工程量", "单价", "合价", "备注"),
                height=220, dxfattribs={"layer": "预算-项目"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 50

    for category, sub_items in items.items():
        msp.add_text("【%s】" % category, height=250,
                    dxfattribs={"layer": "预算-项目"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
        y += 45

        cat_total = 0
        for name, qty, price_info in sub_items:
            unit = price_info.get("unit", "")
            price = price_info.get("price", 0)
            total = qty * price
            cat_total += total
            msp.add_text("%-20s %8.1f %-6s %8.0f %12.0f" % (name[:20], qty, unit, price, total),
                        height=180, dxfattribs={"layer": "预算-金额"}).set_placement((220, y), align=TextEntityAlignment.LEFT)
            y += 35

        msp.add_text("小计: %.0f 元" % cat_total, height=200,
                    dxfattribs={"layer": "预算-合计"}).set_placement((600, y), align=TextEntityAlignment.LEFT)
        grand_total += cat_total
        y += 50

    # 总合计
    y += 30
    msp.add_text("=" * 50, height=250, dxfattribs={"layer": "预算-合计"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 45
    msp.add_text("总预算: %.0f 元" % grand_total, height=350,
                dxfattribs={"layer": "预算-合计"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 50

    # 管理费 10%
    management = grand_total * 0.10
    msp.add_text("管理费(10%%): %.0f 元" % management, height=250,
                dxfattribs={"layer": "预算-合计"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 45
    msp.add_text("含税总价(含管理费): %.0f 元" % (grand_total + management), height=350,
                dxfattribs={"layer": "预算-合计"}).set_placement((200, y), align=TextEntityAlignment.LEFT)
    y += 50
    msp.add_text("以上报价仅供参考，以实际采购和施工为准", height=200,
                dxfattribs={"layer": "预算-说明"}).set_placement((200, y), align=TextEntityAlignment.LEFT)

    doc.saveas(dxf_output_path)

    # 保存 JSON
    budget_data = {
        "total_area_m2": round(total_floor, 1),
        "total_budget": round(grand_total + management),
        "categories": {}
    }
    for cat, sub_items in items.items():
        budget_data["categories"][cat] = {
            "items": [{"name": n, "qty": q, "unit": p["unit"], "price": p["price"],
                       "total": round(q * p["price"])} for n, q, p in sub_items],
            "total": round(sum(q * p["price"] for _, q, p in sub_items))
        }
    json_path = os.path.join(out_dir, "预算报价.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(budget_data, f, ensure_ascii=False, indent=2)

    print("总预算: %.0f 元 (含管理费)" % (grand_total + management))
    return dxf_output_path, json_path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/设计条件.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "../templates/concept_output/预算报价.dxf"
    r, j = calculate_budget(inp, out)
    print("DXF:", r)
    print("JSON:", j)
