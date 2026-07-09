"""
工程量计算器 v2 - 从 Scene3D 实际几何精确算量
项目唯一数据源: Scene3D
"""
import math, json, os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Quantities:
    """工程量计算结果"""
    total_floor_area: float = 0        # 总地面面积 (m2)
    total_wall_area: float = 0         # 总墙面净面积 (扣除门窗, m2)
    total_ceiling_area: float = 0      # 总天花面积 (m2)
    total_perimeter: float = 0         # 总周长 (m)
    door_count: int = 0
    window_count: int = 0
    opening_area: float = 0            # 门窗面积合计 (m2)
    room_count: int = 0
    rooms_detail: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def calculate_from_scene(scene) -> Quantities:
    """
    从 Scene3D 精确计算工程量

    Args:
        scene: Scene3D 对象

    Returns:
        Quantities 数据类，包含所有工程量
    """
    from core.scene3d import Scene3D
    if not isinstance(scene, Scene3D):
        raise TypeError(f"Expected Scene3D, got {type(scene)}")

    q = Quantities()

    # 从场景房间几何计算
    for room in scene.rooms.values():
        area = room.area_m2
        perimeter_m = room.perimeter_mm / 1000
        # 墙面积：周长 x 层高
        wall_area = perimeter_m * (room.ceiling_height_mm / 1000)

        q.total_floor_area += area
        q.total_ceiling_area += area
        q.total_perimeter += perimeter_m
        q.total_wall_area += wall_area

        q.rooms_detail.append({
            "name": room.name,
            "area_m2": round(area, 2),
            "perimeter_m": round(perimeter_m, 2),
            "ceiling_height_m": round(room.ceiling_height_mm / 1000, 2),
            "wall_area_m2": round(wall_area, 2),
            "wall_count": len(room.wall_ids),
            "requirements": room.requirements,
        })

    q.room_count = scene.room_count
    q.door_count = scene.door_count
    q.window_count = scene.window_count

    # 门窗面积从 Opening 实际尺寸计算
    q.opening_area = scene.total_opening_area_m2 or (
        q.door_count * 0.9 * 2.1 + q.window_count * 1.8 * 1.5
    )

    # 墙面面积扣除门窗
    q.total_wall_area = max(0, q.total_wall_area - q.opening_area)

    # 取整
    for field_name in ["total_floor_area", "total_wall_area", "total_ceiling_area",
                       "total_perimeter", "opening_area"]:
        setattr(q, field_name, round(getattr(q, field_name), 2))

    if q.opening_area > 0:
        q.notes.append(
            f"扣除门 {q.door_count} 扇、窗 {q.window_count} 扇，开口面积合计 {q.opening_area:.1f} m²"
        )

    return q


def generate_pricing(quantities: Quantities, region: str = "national_avg") -> list[dict]:
    """
    根据工程量生成报价明细

    Args:
        quantities: Quantities 对象
        region: 地区 ("一线"|"新一线"|"二线"|"三线"|"national_avg")

    Returns:
        报价明细列表
    """
    # 加载地区价格
    prices_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "resources", "regional_prices.json"
    )
    rates = {}
    if os.path.exists(prices_path):
        with open(prices_path, "r", encoding="utf-8") as f:
            price_data = json.load(f)
        rates = price_data.get("tiers", {}).get(region, price_data.get("national_avg", {}))

    # 默认人工费率 (元/m2 或 元/m)
    defaults = {
        "水电改造": 160, "防水工程": 65, "地砖铺贴": 75, "墙砖铺贴": 85,
        "吊顶": 120, "墙面批灰油漆": 35, "踢脚线": 25,
        "开关插座": 15, "灯具安装": 30, "保洁": 1500, "垃圾清运": 2000,
    }

    area = quantities.total_floor_area
    wall = quantities.total_wall_area

    items = []

    # 水电
    water_elec_rate = rates.get("水电_m2", defaults["水电改造"])
    items.append({"category": "水电工程", "item": "水电改造", "qty": area, "unit": "m²",
                  "price": water_elec_rate, "total": round(area * water_elec_rate, 2)})
    items.append({"category": "水电工程", "item": "开关插座安装", "qty": max(40, int(area * 0.8)),
                  "unit": "个", "price": defaults["开关插座"],
                  "total": round(max(40, int(area * 0.8)) * defaults["开关插座"], 2)})

    # 泥瓦
    mason_rate = rates.get("瓦工_m2", defaults["地砖铺贴"])
    waterproof_rate = rates.get("瓦工_m2", defaults["防水工程"]) * 0.85
    items.append({"category": "泥瓦工程", "item": "防水工程", "qty": min(40, round(area, 0)),
                  "unit": "m²", "price": round(waterproof_rate, 2),
                  "total": round(min(40, area) * waterproof_rate, 2)})
    items.append({"category": "泥瓦工程", "item": "地砖铺贴", "qty": area, "unit": "m²",
                  "price": mason_rate, "total": round(area * mason_rate, 2)})
    items.append({"category": "泥瓦工程", "item": "墙砖铺贴", "qty": round(wall * 0.3, 2),
                  "unit": "m²", "price": defaults["墙砖铺贴"],
                  "total": round(wall * 0.3 * defaults["墙砖铺贴"], 2)})

    # 木工吊顶
    wood_rate = rates.get("木工_m2", defaults["吊顶"])
    items.append({"category": "木工/吊顶", "item": "吊顶工程",
                  "qty": quantities.total_ceiling_area, "unit": "m²",
                  "price": wood_rate,
                  "total": round(quantities.total_ceiling_area * wood_rate, 2)})
    items.append({"category": "木工/吊顶", "item": "踢脚线",
                  "qty": round(quantities.total_perimeter, 2), "unit": "m",
                  "price": defaults["踢脚线"],
                  "total": round(quantities.total_perimeter * defaults["踢脚线"], 2)})

    # 油漆
    paint_rate = rates.get("油漆_m2", defaults["墙面批灰油漆"])
    paint_area = wall + quantities.total_ceiling_area
    items.append({"category": "油漆工程", "item": "墙面批灰油漆",
                  "qty": round(paint_area, 2), "unit": "m²",
                  "price": paint_rate, "total": round(paint_area * paint_rate, 2)})

    # 拆除
    demo_rate = rates.get("拆除_m2", 42)
    if demo_rate > 0:
        items.append({"category": "拆除工程", "item": "原装修拆除",
                      "qty": area, "unit": "m²", "price": demo_rate,
                      "total": round(area * demo_rate, 2)})

    # 其他
    items.append({"category": "其他", "item": "保洁", "qty": 1, "unit": "项",
                  "price": defaults["保洁"], "total": defaults["保洁"]})
    items.append({"category": "其他", "item": "垃圾清运", "qty": 1, "unit": "项",
                  "price": defaults["垃圾清运"], "total": defaults["垃圾清运"]})

    # 管理费 (根据项目大小调整比例)
    subtotal = sum(it["total"] for it in items)
    mgmt_rate = 0.05 if area > 150 else 0.08
    items.append({"category": "管理费", "item": f"管理费({int(mgmt_rate*100)}%)",
                  "qty": 1, "unit": "项",
                  "price": round(subtotal * mgmt_rate, 2),
                  "total": round(subtotal * mgmt_rate, 2)})

    return items


def calculate_and_price(scene, region: str = "national_avg") -> tuple:
    """
    一站式: 从 Scene3D 算量 + 报价

    Returns:
        (Quantities, pricing_list)
    """
    q = calculate_from_scene(scene)
    pricing = generate_pricing(q, region)
    return q, pricing
