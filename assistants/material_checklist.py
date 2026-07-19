"""
材料清单生成器 v2 - 从 Scene3D 房间实际面积和风格偏好计算
项目唯一数据源: Scene3D
"""
import math, json, os

# 材料规格数据库
MATERIAL_DB = {
    "地面": {
        "瓷砖800x800": {"unit": "片", "spec": "800x800mm", "m2_per_unit": 0.64, "waste_rate": 0.05},
        "瓷砖600x600": {"unit": "片", "spec": "600x600mm", "m2_per_unit": 0.36, "waste_rate": 0.05},
        "瓷砖300x600": {"unit": "片", "spec": "300x600mm", "m2_per_unit": 0.18, "waste_rate": 0.05},
        "实木地板": {"unit": "m2", "spec": "标准规格", "m2_per_unit": 1, "waste_rate": 0.08},
        "复合地板": {"unit": "m2", "spec": "标准规格", "m2_per_unit": 1, "waste_rate": 0.05},
        "木纹砖": {"unit": "m2", "spec": "木纹规格", "m2_per_unit": 1, "waste_rate": 0.05},
        "防滑地砖": {"unit": "m2", "spec": "300x300mm", "m2_per_unit": 1, "waste_rate": 0.05},
        "大理石": {"unit": "m2", "spec": "定制规格", "m2_per_unit": 1, "waste_rate": 0.10},
        "微水泥": {"unit": "m2", "spec": "批刮型", "m2_per_unit": 1, "waste_rate": 0.03},
    },
    "墙面": {
        "乳胶漆": {"unit": "桶", "spec": "18L/桶", "m2_per_unit": 80, "waste_rate": 0.03},
        "墙布": {"unit": "m2", "spec": "标准宽幅", "m2_per_unit": 1, "waste_rate": 0.10},
        "墙砖300x600": {"unit": "片", "spec": "300x600mm", "m2_per_unit": 0.18, "waste_rate": 0.05},
        "木饰面": {"unit": "m2", "spec": "定制规格", "m2_per_unit": 1, "waste_rate": 0.08},
        "微水泥": {"unit": "m2", "spec": "批刮型", "m2_per_unit": 1, "waste_rate": 0.03},
    }
}

# 风格→默认材质映射
STYLE_MATERIAL_MAP = {
    "现代简约": {"floor": "瓷砖800x800", "wall": "乳胶漆"},
    "新中式": {"floor": "木纹砖", "wall": "乳胶漆"},
    "北欧": {"floor": "复合地板", "wall": "乳胶漆"},
    "日式": {"floor": "实木地板", "wall": "乳胶漆"},
    "轻法式": {"floor": "实木地板", "wall": "墙布"},
    "工业风": {"floor": "微水泥", "wall": "微水泥"},
    "美式": {"floor": "实木地板", "wall": "乳胶漆"},
    "混搭": {"floor": "复合地板", "wall": "乳胶漆"},
}


def generate_material_checklist(scene, style_prefs: dict = None) -> dict:
    """
    从 Scene3D 生成材料清单

    Args:
        scene: Scene3D 对象
        style_prefs: 风格偏好 dict (可选，优先于场景内置 style)

    Returns:
        {"items": [...], "summary": [...]}
    """
    from core.scene3d import Scene3D
    if not isinstance(scene, Scene3D):
        raise TypeError(f"Expected Scene3D, got {type(scene)}")

    style = style_prefs or scene.style or {}
    primary_style = style.get("primary_style", "")

    # 从风格推导默认材质
    style_defaults = STYLE_MATERIAL_MAP.get(primary_style, {"floor": "复合地板", "wall": "乳胶漆"})
    floor_mat = style.get("floor_material", "") or style_defaults["floor"]
    wall_mat = style.get("wall_material", "") or style_defaults["wall"]

    items = []
    for room in scene.rooms.values():
        name = room.name
        area = room.area_m2
        perimeter_m = room.perimeter_mm / 1000
        ceiling_h = room.ceiling_height_mm / 1000

        # 地面材料
        floor_spec = MATERIAL_DB["地面"].get(floor_mat) or MATERIAL_DB["地面"]["复合地板"]
        waste = area * floor_spec["waste_rate"]
        if floor_spec["unit"] == "片":
            qty = math.ceil((area + waste) / floor_spec["m2_per_unit"])
            inc_waste = qty
        else:
            qty = round(area, 2)
            inc_waste = round(area + waste, 2)

        items.append({
            "category": "地面",
            "room": name,
            "material": floor_mat,
            "quantity": qty,
            "unit": floor_spec["unit"],
            "waste_rate": floor_spec["waste_rate"],
            "including_waste": inc_waste,
            "spec": floor_spec["spec"],
        })

        # 墙面材料
        wall_area = perimeter_m * ceiling_h
        # 扣除门窗 (按场景实际)
        door_area = 0
        window_area = 0
        for wid in room.wall_ids:
            w = scene.walls.get(wid)
            if w:
                for op in w.openings:
                    op_area_m2 = op.width_mm * op.height_mm / 1e6
                    if op.type.value == "door":
                        door_area += op_area_m2
                    else:
                        window_area += op_area_m2
        net_wall = max(0, wall_area - door_area - window_area)

        wall_spec = MATERIAL_DB["墙面"].get(wall_mat) or MATERIAL_DB["墙面"]["乳胶漆"]
        w_waste = net_wall * wall_spec["waste_rate"]

        if wall_spec["unit"] == "桶":
            qty_w = max(1, math.ceil((net_wall + w_waste) / wall_spec["m2_per_unit"]))
            inc_w = qty_w
        else:
            qty_w = round(net_wall, 2)
            inc_w = round(net_wall + w_waste, 2)

        items.append({
            "category": "墙面",
            "room": name,
            "material": wall_mat,
            "quantity": qty_w,
            "unit": wall_spec["unit"],
            "waste_rate": wall_spec["waste_rate"],
            "including_waste": inc_w,
            "spec": wall_spec["spec"],
        })

        # 踢脚线
        items.append({
            "category": "辅材",
            "room": name,
            "material": "踢脚线",
            "quantity": round(perimeter_m, 2),
            "unit": "m",
            "waste_rate": 0.08,
            "including_waste": round(perimeter_m * 1.08, 2),
            "spec": "标准规格",
        })

    # 汇总
    summary = {}
    for item in items:
        key = (item["category"], item["material"])
        if key not in summary:
            summary[key] = {
                "category": item["category"],
                "material": item["material"],
                "quantity": 0, "unit": item["unit"],
                "including_waste": 0, "spec": item["spec"],
                "rooms": [],
            }
        s = summary[key]
        # 按单位汇总
        if item["unit"] == "片":
            s["quantity"] += item["quantity"]
            s["including_waste"] += item["including_waste"]
        else:
            s["quantity"] += item["quantity"]
            s["including_waste"] += item["including_waste"]
        s["rooms"].append(item["room"])

    for k, v in summary.items():
        v["quantity"] = round(v["quantity"], 2)
        v["including_waste"] = round(v["including_waste"], 2)

    return {
        "items": items,
        "summary": list(summary.values()),
        "style_note": f"风格: {primary_style}, 地面: {floor_mat}, 墙面: {wall_mat}",
    }
