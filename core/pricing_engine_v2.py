import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.furniture_library import get_library as get_flib
from core.material_library import get_library as get_mlib

PRICES = {
    'wall_masonry_per_m2': 120, 'wall_plaster_per_m2': 35,
    'floor_tile_per_m2': 80, 'floor_wood_per_m2': 60,
    'ceiling_gypsum_per_m2': 90, 'door_install_per_unit': 500,
    'window_install_per_unit': 400, 'electrical_per_m2': 80,
    'plumbing_per_m2': 60, 'waterproof_per_m2': 50,
    'labor_overhead_pct': 0.15, 'design_fee_pct': 0.05,
    'contingency_pct': 0.10,
}

def estimate_full_budget(scene):
    flib = get_flib(); mlib = get_mlib()
    items = []

    # AREA: collect all room areas
    room_areas = {}
    total_floor_area = 0
    if hasattr(scene, 'rooms') and scene.rooms:
        for rid, room in scene.rooms.items():
            pts = getattr(room, 'floor_points', [])
            area = 0
            if pts and len(pts) >= 3:
                s = 0; n = len(pts)
                for i in range(n):
                    j = (i + 1) % n
                    s += pts[i].x * pts[j].z - pts[j].x * pts[i].z
                area = abs(s) / 2 / 1e6
            room_areas[getattr(room, 'name', rid)] = area if area > 0 else 15
            total_floor_area += room_areas[getattr(room, 'name', rid)]

    # WALLS
    for wid, wall in scene.walls.items():
        l = ((wall.end.x - wall.start.x)**2 + (wall.end.z - wall.start.z)**2)**0.5
        area = l * wall.height_mm / 1e6
        items.append({'name': f'墙体 {wid}', 'cat': 'construction', 'qty': round(area, 1), 'unit': 'm2',
                       'up': PRICES['wall_masonry_per_m2'], 'amt': round(area * PRICES['wall_masonry_per_m2'])})
        items.append({'name': f'抹灰 {wid}', 'cat': 'construction', 'qty': round(area, 1), 'unit': 'm2',
                       'up': PRICES['wall_plaster_per_m2'], 'amt': round(area * PRICES['wall_plaster_per_m2'])})

    # FLOORS + CEILINGS
    for rname, area in room_areas.items():
        items.append({'name': f'{rname} 地面', 'cat': 'construction', 'qty': round(area, 1), 'unit': 'm2',
                       'up': PRICES['floor_tile_per_m2'], 'amt': round(area * PRICES['floor_tile_per_m2'])})
        items.append({'name': f'{rname} 吊顶', 'cat': 'construction', 'qty': round(area, 1), 'unit': 'm2',
                       'up': PRICES['ceiling_gypsum_per_m2'], 'amt': round(area * PRICES['ceiling_gypsum_per_m2'])})

    # DOORS + WINDOWS
    for wid, wall in scene.walls.items():
        for op in wall.openings:
            t = '门' if op.type.value == 'door' else '窗'
            up = PRICES['door_install_per_unit'] if op.type.value == 'door' else PRICES['window_install_per_unit']
            items.append({'name': f'{t} {op.id}', 'cat': 'construction', 'qty': 1, 'unit': 'unit', 'up': up, 'amt': up})

    # FURNITURE - use spec_id for exact pricing
    if hasattr(scene, 'furniture') and scene.furniture:
        furns = scene.furniture.values() if isinstance(scene.furniture, dict) else scene.furniture
        for f in furns:
            name = getattr(f, 'name', 'unknown')
            sid = getattr(f, 'spec_id', '')
            spec = flib.catalog.get(sid) if sid else None
            if spec:
                price = round((spec.price_range_low + spec.price_range_high) / 2)
            else:
                price = flib.catalog.get(name, None)
                price = round((price.price_range_low + price.price_range_high) / 2) if price else 500
            items.append({'name': f'家具 {name}', 'cat': 'furniture', 'qty': 1, 'unit': 'unit', 'up': price, 'amt': price})

    # MATERIALS - use actual area from scene.materials
    if hasattr(scene, 'materials') and scene.materials:
        for room_name, mats in scene.materials.items():
            for mat_key, mat_val in mats.items():
                if isinstance(mat_val, dict):
                    up = mat_val.get('price_m2', 0)
                    area = mat_val.get('area_m2', room_areas.get(room_name, 15))
                else:
                    ms = mlib.get(str(mat_val))
                    up = ms.price_per_m2 if ms else 0
                    area = room_areas.get(room_name, 15)
                items.append({'name': f'材料 {room_name}/{mat_key}', 'cat': 'material', 'qty': round(area, 1), 'unit': 'm2', 'up': up, 'amt': round(up * area)})

    # SUMMARIES
    con = sum(i['amt'] for i in items if i['cat'] == 'construction')
    furn = sum(i['amt'] for i in items if i['cat'] == 'furniture')
    mat = sum(i['amt'] for i in items if i['cat'] == 'material')
    sub = con + furn + mat
    labor = round(sub * PRICES['labor_overhead_pct'])
    design = round(sub * PRICES['design_fee_pct'])
    cont = round(sub * PRICES['contingency_pct'])
    total = sub + labor + design + cont

    return {
        'project': scene.name,
        'total_floor_area_m2': round(total_floor_area, 1),
        'summary': {'construction': con, 'furniture': furn, 'materials': mat,
                    'subtotal': sub, 'labor_overhead': labor, 'design_fee': design,
                    'contingency': cont, 'total': total},
        'items': items,
    }

print('pricing_engine_v3 ready')
