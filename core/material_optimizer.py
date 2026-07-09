# -*- coding: utf-8 -*-
"""
material_optimizer - Material quantity optimization & waste reduction
Calculates optimal cutting patterns for tiles, flooring, boards.
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass
class MaterialOrder:
    name: str
    unit: str
    net_quantity: float
    waste_rate: float
    gross_quantity: float
    unit_price: float
    total_cost: float
    optimization_notes: str = ""

def optimize_materials(scene) -> list:
    """Calculate material quantities with waste optimization."""
    rooms = [_norm(r) for r in (get_rooms(scene))]
    walls = [_norm(w) for w in (get_walls(scene))]
    
    orders = []
    
    # Floor area per room type
    floor_areas = {}
    for r in rooms:
        rt = r.get('type', 'other')
        area = r.get('length_mm', 0) * r.get('width_mm', 0) / 1e6
        floor_areas[rt] = floor_areas.get(rt, 0) + area
    
    total_floor = sum(floor_areas.values())
    
    # ---- Flooring ----
    # Tiles: 800x800mm = 0.64m2 per tile
    tile_area = floor_areas.get('厨房', 0) + floor_areas.get('kitchen', 0) + floor_areas.get('卫生间', 0) + floor_areas.get('bathroom', 0)
    if tile_area > 0:
        tiles_per_m2 = 1 / 0.64  # 800x800
        net_tiles = math.ceil(tile_area * tiles_per_m2)
        waste = math.ceil(net_tiles * 0.08)  # 8% cutting waste
        orders.append(MaterialOrder(
            "瓷砖 800x800mm", "片",
            net_tiles, 0.08, net_tiles + waste,
            unit_price=55, total_cost=(net_tiles + waste) * 55,
            optimization_notes="标准铺贴，损耗约8%。建议多备1箱用于后期维修"
        ))
    
    # Wood flooring: living + bedroom
    wood_area = floor_areas.get('客厅', 0) + floor_areas.get('living_room', 0) + floor_areas.get('主卧', 0) + floor_areas.get('bedroom', 0) + floor_areas.get('书房', 0) + floor_areas.get('study', 0) + floor_areas.get('餐厅', 0) + floor_areas.get('dining', 0)
    if wood_area > 0:
        net_planks = math.ceil(wood_area / (1.2 * 0.19))  # Standard plank 1200x190mm
        waste = math.ceil(net_planks * 0.05)  # 5% for staggered pattern
        orders.append(MaterialOrder(
            "实木复合地板 1200x190mm", "片",
            net_planks, 0.05, net_planks + waste,
            unit_price=22, total_cost=(net_planks + waste) * 22,
            optimization_notes="1/3错缝铺贴，损耗约5%。注意顺光方向"
        ))
    
    # ---- Wall paint ----
    total_wall = total_floor * 2.5  # Rough estimate
    if total_wall > 0:
        paint_per_sqm = 0.25  # L per m2 for 2 coats
        net_paint = total_wall * paint_per_sqm
        buckets_18L = math.ceil(net_paint / 18)
        orders.append(MaterialOrder(
            "乳胶漆 18L/桶", "桶",
            net_paint, 0, buckets_18L,
            unit_price=380, total_cost=buckets_18L * 380,
            optimization_notes=f"底漆1遍+面漆2遍，约{net_paint:.1f}L。{buckets_18L}桶可覆盖{buckets_18L*18/paint_per_sqm:.0f}m2"
        ))
    
    # ---- Wall tiles (kitchen + bathroom) ----
    wall_tile_area = 0
    for r in rooms:
        rt = r.get('type', '')
        if rt in ('厨房', 'kitchen', '卫生间', 'bathroom'):
            wall_tile_area += (r.get('length_mm',0) + r.get('width_mm',0)) * 2 * 2.4 / 1e6  # 2.4m high
    
    if wall_tile_area > 0:
        tiles_300x600 = math.ceil(wall_tile_area / 0.18)
        waste = math.ceil(tiles_300x600 * 0.1)
        orders.append(MaterialOrder(
            "墙砖 300x600mm", "片",
            tiles_300x600, 0.10, tiles_300x600 + waste,
            unit_price=8, total_cost=(tiles_300x600 + waste) * 8,
            optimization_notes="标准铺贴+阴阳角切割，损耗约10%"
        ))
    
    # ---- Mortar / Grout ----
    mortar_kg = total_floor * 25 + wall_tile_area * 20  # kg per m2
    orders.append(MaterialOrder(
        "瓷砖胶/水泥砂浆", "kg",
        mortar_kg, 0.05, math.ceil(mortar_kg * 1.05 / 25) * 25,
        unit_price=1.2, total_cost=math.ceil(mortar_kg * 1.05 / 25) * 25 * 1.2,
        optimization_notes="地面25kg/m2 + 墙面20kg/m2。25kg/袋计"
    ))
    
    # ---- Summary ----
    total = sum(o.total_cost for o in orders)
    orders.append(MaterialOrder(
        "=== 材料总计 ===", "",
        0, 0, 0, 0, total,
        f"共{len(orders)-1}类材料"
    ))
    
    return orders

from core.scene_utils import normalize as _n, get_rooms, get_walls, get_doors, get_windows
_norm = _n  # alias for modules that use _norm