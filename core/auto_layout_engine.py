import json, os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.furniture_library import get_library as get_furniture_lib
from core.material_library import get_library as get_material_lib

def auto_furnish(scene, style='modern', use_ai=True):
    from core.scene3d import Furniture, Point3D
    flib = get_furniture_lib(); mlib = get_material_lib()
    placements = []; rooms = _get_rooms(scene)
    for room in rooms:
        rname = room['name']; rtype = room['type']
        rlen = room['length_mm']; rwid = room['width_mm']; rarea = room.get('area_m2', rlen*rwid/1e6)
        specs = flib.get_room_defaults(rtype) or flib.get_room_defaults('living')
        styled = [s for s in specs if style in s.styles] or specs
        layout = _ai_place(styled, rname, rlen, rwid, rtype, style) if use_ai else _rule_place(styled, rname, rlen, rwid)
        for item in layout:
            item['room_area_m2'] = rarea
            placements.append(item)
    existing_names = set()
    if hasattr(scene, 'furniture') and scene.furniture:
        if isinstance(scene.furniture, dict):
            existing_names = {f.name for f in scene.furniture.values()}
        elif isinstance(scene.furniture, list):
            existing_names = {f.name for f in scene.furniture}
    if not hasattr(scene, 'furniture'):
        scene.furniture = []
    for p in placements:
        if p['name'] in existing_names: continue
        furn = Furniture(
            id=p['id'], name=p['name'], category=p['category'],
            position=Point3D(p['position'][0], p['position'][1], p['position'][2]),
            rotation_deg=p['rotation'], width_mm=p['width_mm'], depth_mm=p['depth_mm'],
            height_mm=p['height_mm'], room_id=p['room'],
            model_path=p.get('model_path', ''))
        # Store spec_id and price on the furniture object
        furn.spec_id = p.get('spec_id', '')
        furn.price_range = p.get('price_range', [0, 0])
        if isinstance(scene.furniture, list):
            scene.furniture.append(furn)
        else:
            scene.furniture[furn.id] = furn
        existing_names.add(p['name'])
    # Assign materials with actual room areas
    scene.materials = {}
    for room in rooms:
        rtype = room['type']; rarea = room.get('area_m2', room['length_mm']*room['width_mm']/1e6)
        mats = mlib.get_defaults_for_room(rtype)
        scene.materials[room['name']] = {
            k: {'id': v.id, 'name': v.name, 'color': v.color_hex,
                'price_m2': v.price_per_m2, 'area_m2': rarea}
            for k, v in mats.items()
        }
    print(f'[AutoFurnish] {len(placements)} pieces in {len(rooms)} rooms')
    return placements

def _get_rooms(scene):
    rooms = []
    if hasattr(scene, 'rooms') and scene.rooms:
        for rid, room in scene.rooms.items():
            rtype = 'living'
            name = getattr(room, 'name', rid)
            n = name.lower()
            if 'bed' in n or '主卧' in n or '次卧' in n: rtype = 'bedroom'
            elif 'din' in n or '餐' in n: rtype = 'dining'
            elif 'kitchen' in n or '厨' in n: rtype = 'kitchen'
            elif 'bath' in n or '卫' in n or '浴' in n: rtype = 'bathroom'
            elif 'study' in n or '书' in n: rtype = 'study'
            elif 'entry' in n or '玄' in n: rtype = 'entry'
            pts = getattr(room, 'floor_points', [])
            area_m2 = 0
            if pts and len(pts) >= 3:
                s = 0; n_pts = len(pts)
                for i in range(n_pts):
                    j = (i + 1) % n_pts
                    s += pts[i].x * pts[j].z - pts[j].x * pts[i].z
                area_m2 = abs(s) / 2 / 1e6
            xs = [p.x for p in pts] if pts else [0, 4000]
            zs = [p.z for p in pts] if pts else [0, 3500]
            lmm = max(zs) - min(zs) if pts else 4000
            wmm = max(xs) - min(xs) if pts else 3500
            rooms.append({'name': name, 'type': rtype, 'length_mm': lmm, 'width_mm': wmm,
                          'height_mm': getattr(room, 'ceiling_height_mm', 2800), 'area_m2': area_m2 if area_m2 > 0 else lmm*wmm/1e6})
    return rooms

def _rule_place(specs, rname, rlen, rwid):
    results = []; cx = rlen / 2; cy = rwid / 2
    for i, spec in enumerate(specs):
        fid = f'furn-{uuid.uuid4().hex[:8]}'
        if spec.category == 'bed': x, z, rot = cx - spec.width_mm/2 + i*200, 300 + i*100, 0
        elif spec.category == 'sofa': x, z, rot = cx - spec.width_mm/2, cy - spec.depth_mm - 300, 0
        elif spec.category in ('table', 'chair'): x, z, rot = cx - spec.width_mm/2 + i*200, cy + spec.depth_mm/2 + 300, 0
        elif spec.category == 'cabinet': x, z, rot = 100, cy - spec.depth_mm/2 + i*200, 0
        elif spec.category == 'lighting': x, z, rot = cx - spec.width_mm/2, cy - spec.depth_mm/2, 0
        elif spec.category == 'decor': x, z, rot = 500 + i*300, 500 + i*200, 0
        elif spec.category == 'fixture': x, z, rot = 200 + i*200, cy - spec.depth_mm/2, 0
        else: x, z, rot = cx - spec.width_mm/2 + i*150, 500 + i*200, 0
        results.append({
            'id': fid, 'name': spec.name, 'category': spec.category,
            'position': [x, 0, z], 'rotation': rot,
            'width_mm': spec.width_mm, 'depth_mm': spec.depth_mm,
            'height_mm': spec.height_mm, 'room': rname,
            'model_path': spec.model_path, 'spec_id': spec.id,
            'price_range': [spec.price_range_low, spec.price_range_high],
        })
    return results

def _ai_place(specs, rname, rlen, rwid, rtype, style):
    try:
        from core.ai_client import get_client
        client = get_client()
        if not client.available: return _rule_place(specs, rname, rlen, rwid)
        spec_list = [{'id': s.id, 'name': s.name, 'cat': s.category, 'w': s.width_mm, 'd': s.depth_mm, 'h': s.height_mm} for s in specs]
        prompt = f'Interior designer. Room: {rname}({rtype}), {rlen}x{rwid}mm. Style: {style}. Place furniture: {json.dumps(spec_list, ensure_ascii=False)}. Return JSON array: [{{"spec_id":"...","name":"...","category":"...","position":[x,0,z],"rotation":0,"width_mm":W,"depth_mm":D,"height_mm":H}}]. Rules: 600mm walkways, within bounds, no overlap. JSON only.'
        resp = client.chat(prompt, temperature=0.3, max_tokens=2000)
        import re; m = re.search(r'\[.*\]', resp, re.DOTALL)
        if m:
            placements = json.loads(m.group())
            for p in placements:
                p.setdefault('id', f'furn-{uuid.uuid4().hex[:8]}'); p.setdefault('room', rname); p.setdefault('model_path', '')
                for s in specs:
                    if s.id == p.get('spec_id'): p.setdefault('price_range', [s.price_range_low, s.price_range_high]); break
            return placements
    except Exception as e: print(f'[AI Layout] Fallback: {e}')
    return _rule_place(specs, rname, rlen, rwid)

def assign_materials(scene, style='modern'):
    mlib = get_material_lib(); rooms = _get_rooms(scene)
    if not hasattr(scene, 'materials'): scene.materials = {}
    for room in rooms:
        mats = mlib.get_defaults_for_room(room['type'])
        rarea = room.get('area_m2', room['length_mm']*room['width_mm']/1e6)
        scene.materials[room['name']] = {
            k: {'id': v.id, 'name': v.name, 'color': v.color_hex,
                'price_m2': v.price_per_m2, 'area_m2': rarea}
            for k, v in mats.items()
        }
    return scene.materials

def generate_budget_all(scene):
    from core.pricing_engine import estimate_total_cost
    return estimate_total_cost(scene)

print('auto_layout_engine v4 ready')
