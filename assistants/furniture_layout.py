"""
家具布局引擎 - 确定性规则引擎，非 LLM 猜测
读取 design_rules.json + furniture_catalog.json，
将家具按规则放入 Scene3D
"""
import json, os, math, uuid, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene3d import Scene3D, Room, Furniture, Point3D


def _load_json(filename: str) -> dict:
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# 房间名称→类型映射
ROOM_TYPE_MAP = {
    "客厅": "客厅", "起居室": "客厅", "living": "客厅",
    "主卧": "主卧", "次卧": "主卧", "卧室": "主卧", "儿童房": "主卧",
    "bedroom": "主卧", "master": "主卧",
    "厨房": "厨房", "kitchen": "厨房",
    "卫生间": "卫生间", "厕所": "卫生间", "浴室": "卫生间", "bathroom": "卫生间",
    "餐厅": "餐厅", "dining": "餐厅",
    "书房": "书房", "study": "书房", "办公": "书房",
    "玄关": "客厅", "阳台": "客厅", "走廊": "客厅", "储物间": "主卧",
}

# 家具类型→catalog 键名映射
FURNITURE_TYPE_MAP = {
    "沙发": ["沙发_L型", "沙发_三人", "沙发_双人"],
    "电视柜": ["电视柜"],
    "茶几": ["茶几"],
    "双人床": ["双人床_1.8m", "双人床_1.5m"],
    "衣柜": ["衣柜_三门", "衣柜_双门"],
    "床头柜": ["床头柜"],
    "梳妆台": ["梳妆台"],
    "橱柜": ["橱柜_地柜"],
    "冰箱": ["冰箱_双门"],
    "餐桌": ["餐桌_6人", "餐桌_4人"],
    "餐椅": ["餐椅"],
    "书桌": ["书桌"],
    "书柜": ["书柜"],
    "洗手台": ["洗手台"],
    "马桶": ["马桶"],
    "淋浴房": ["淋浴房_900"],
    "鞋柜": ["鞋柜"],
}


def _classify_room(room_name: str) -> str:
    """将房间名称归类为标准类型"""
    name_lower = room_name.lower()
    for key, rtype in ROOM_TYPE_MAP.items():
        if key in name_lower:
            return rtype
    return "客厅"  # 默认当客厅


def _get_room_bounds(room: Room) -> dict:
    """获取房间的包围盒和朝向信息"""
    if len(room.floor_points) < 3:
        return {"cx": 0, "cz": 0, "min_x": 0, "max_x": 0, "min_z": 0, "max_z": 0,
                "width": 0, "depth": 0}
    xs = [p.x for p in room.floor_points]
    zs = [p.z for p in room.floor_points]
    cx = sum(xs) / len(xs)
    cz = sum(zs) / len(zs)
    return {
        "cx": cx, "cz": cz,
        "min_x": min(xs), "max_x": max(xs),
        "min_z": min(zs), "max_z": max(zs),
        "width": max(xs) - min(xs),
        "depth": max(zs) - min(zs),
    }


def _find_longest_wall(room: Room, scene: Scene3D) -> tuple:
    """找到房间中最长墙的方向和位置(用于沙发/床靠墙)"""
    longest = None
    max_len = 0
    for wid in room.wall_ids:
        w = scene.walls.get(wid)
        if w:
            if w.length_mm > max_len:
                max_len = w.length_mm
                longest = w
    if longest:
        return longest.direction, longest.start, longest.end, longest.length_mm
    return (1, 0), Point3D(), Point3D(), 0


def _pick_furniture(furn_type: str, catalog: dict, room_width: float) -> dict:
    """从家具库中选择合适尺寸的家具"""
    candidates = FURNITURE_TYPE_MAP.get(furn_type, [furn_type])
    for key in candidates:
        if key in catalog:
            item = catalog[key]
            # 检查是否放得下
            if item.get("w", 0) <= room_width * 0.9:
                return item
    # 回退
    for key in candidates:
        if key in catalog:
            return catalog[key]
    return {"w": 1200, "d": 600, "h": 750, "category": "table"}


def apply_layout(scene: Scene3D) -> Scene3D:
    """
    根据设计规则库将家具布局应用到场景中。
    直接向 scene.furniture 添加 Furniture 对象。

    Returns:
        更新后的 Scene3D (原地修改)
    """
    rules = _load_json("design_rules.json")
    catalog = _load_json("furniture_catalog.json")
    catalog_items = catalog.get("items", {})
    clearance = catalog.get("clearance_rules", {})

    layout_rules = rules.get("furniture_layout", {})
    if not layout_rules:
        return scene

    for room in scene.rooms.values():
        rtype = _classify_room(room.name)
        rules_for_room = layout_rules.get(rtype, [])
        if not rules_for_room:
            continue

        bounds = _get_room_bounds(room)
        room_w = bounds["width"]  # X 方向
        room_d = bounds["depth"]  # Z 方向

        for rule in rules_for_room:
            furn_name = rule.get("furniture", "")
            placement = rule.get("rule", "")
            clearance_mm = rule.get("clearance", "")
            distance_val = rule.get("distance_to_tv", 0)
            optional = rule.get("optional", False)

            # 跳过可选家具（小空间）
            if optional and (room_w < 3000 or room_d < 3000):
                continue

            item = _pick_furniture(furn_name, catalog_items, room_w)
            fw = item["w"]
            fd = item["d"]
            fh = item.get("h", 850)
            fcat = item.get("category", "furniture")

            pos_x = bounds["min_x"]
            pos_z = bounds["min_z"]

            if "最长墙" in placement or "靠墙" in placement:
                # 找到最长墙，沿墙放置
                (dx, dz), w_start, w_end, w_len = _find_longest_wall(room, scene)
                if w_len > 0:
                    # 沿墙居中放置
                    mid_x = (w_start.x + w_end.x) / 2
                    mid_z = (w_start.z + w_end.z) / 2
                    # 法向量方向偏移
                    nx, nz = -dz, dx
                    pos_x = mid_x - fw / 2 * dx
                    pos_z = mid_z - fw / 2 * dz
                    # 靠墙偏移
                    pos_x += nx * (fd / 2 + 10)
                    pos_z += nz * (fd / 2 + 10)

            elif "居中" in placement:
                pos_x = bounds["cx"] - fw / 2
                pos_z = bounds["cz"] - fd / 2

            elif "靠窗" in placement:
                pos_x = bounds["max_x"] - fw - 200
                pos_z = bounds["cz"] - fd / 2

            elif "前" in placement or "侧" in placement:
                # 相对位置：找已放置的同房家具
                existing = [f for f in scene.furniture.values() if f.room_id == room.id]
                if existing:
                    ref = existing[-1]
                    pos_x = ref.position.x + ref.width_mm + 400
                    pos_z = ref.position.z

            elif "角落" in placement:
                pos_x = bounds["min_x"] + 100
                pos_z = bounds["max_z"] - fd - 100

            elif "入口" in placement:
                pos_x = bounds["min_x"] + 100
                pos_z = bounds["min_z"] + 100

            # 约束在房间内
            pos_x = max(bounds["min_x"] + 50, min(pos_x, bounds["max_x"] - fw - 50))
            pos_z = max(bounds["min_z"] + 50, min(pos_z, bounds["max_z"] - fd - 50))

            furn = Furniture(
                id=f"furn-{uuid.uuid4().hex[:8]}",
                name=furn_name,
                category=fcat,
                position=Point3D(x=pos_x, y=0, z=pos_z),
                width_mm=fw,
                depth_mm=fd,
                height_mm=fh,
                room_id=room.id,
            )
            scene.furniture[furn.id] = furn

    return scene


def generate_layout_report(scene: Scene3D) -> dict:
    """生成布局报告"""
    by_room = {}
    for furn in scene.furniture.values():
        room = scene.rooms.get(furn.room_id)
        rname = room.name if room else "未知"
        if rname not in by_room:
            by_room[rname] = []
        by_room[rname].append({
            "name": furn.name,
            "size": f"{furn.width_mm:.0f}x{furn.depth_mm:.0f}x{furn.height_mm:.0f}mm",
            "position": f"({furn.position.x:.0f}, {furn.position.z:.0f})",
        })

    return {
        "total_furniture": len(scene.furniture),
        "rooms": {k: {"count": len(v), "items": v} for k, v in by_room.items()},
    }
