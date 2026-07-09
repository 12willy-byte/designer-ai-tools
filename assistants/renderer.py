import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene3d import Scene3D

TEMPLATE = open(os.path.join(os.path.dirname(__file__), '_threejs_template.html'), 'r', encoding='utf-8').read()

def export_threejs_html(scene, output_path):
    data = _prepare(scene)
    name = scene.name or '3D Scene'
    room_count = getattr(scene, 'room_count', len(data.get('rooms', [])))
    wall_count = len(data.get('walls', []))
    area = data.get('total_area', 0)
    summary = 'Rooms: {} | Walls: {} | Area: {:.1f}m2'.format(room_count, wall_count, area)
    r = len(data.get('rooms', [])); w = len(data.get('walls', []))
    d = data.get('doors', 0); win = data.get('windows', 0); f = len(data.get('furniture', []))
    stats = 'Rooms {} | Walls {} | Doors {} | Windows {} | Furniture {}'.format(r, w, d, win, f)
    html = TEMPLATE.replace('__TITLE__', name)
    html = html.replace('__SUMMARY__', summary)
    html = html.replace('__DATA__', json.dumps(data, ensure_ascii=False))
    html = html.replace('__STATS__', stats)
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path

def _prepare(scene):
    """Prepare scene data for Three.js rendering."""
    import math
    walls = []
    for w in scene.walls.values():
        ops = []
        for o in w.openings:
            ops.append({
                'off': round(o.offset_mm/1000, 3),
                'w': round(o.width_mm/1000, 3),
                'h': round(o.height_mm/1000, 3),
                'sill': round(o.sill_height_mm/1000, 3),
                'type': o.type.value
            })
        # Calculate wall in meters, offset to positive space
        walls.append({
            'sx': round(w.start.x/1000, 3), 'sz': round(w.start.z/1000, 3),
            'ex': round(w.end.x/1000, 3), 'ez': round(w.end.z/1000, 3),
            'h': round(w.height_mm/1000, 3),
            'thick': round(w.thickness_mm/1000, 3),
            'openings': ops,
            'load_bearing': w.is_load_bearing,
        })
    
    rooms = []
    for r in scene.rooms.values():
        pts = []
        for p in r.floor_points:
            pts.append({'x': round(p.x, 1), 'z': round(p.z, 1)})
        rooms.append({
            'floor': pts,
            'name': r.name,
            'type': r.type,
            'area_m2': round(r.area_m2, 1),
            'ceiling_h': round(r.ceiling_height_mm/1000, 1),
        })
    
    furniture = []
    furn = getattr(scene, 'furniture', [])
    items = furn.values() if isinstance(furn, dict) else (furn if isinstance(furn, list) else [])
    for f in items:
        furniture.append({
            'px': round(f.position.x/1000, 3),
            'pz': round(f.position.z/1000, 3),
            'w': round(f.width_mm/1000, 3),
            'd': round(f.depth_mm/1000, 3),
            'h': round(f.height_mm/1000, 3),
            'name': f.name,
            'category': getattr(f, 'category', 'general'),
            'rotation': getattr(f, 'rotation_deg', 0),
        })
    
    beams = []
    for b in scene.beams.values():
        beams.append({
            'px': round(b.position.x/1000, 3),
            'pz': round(b.position.z/1000, 3),
            'w': round(b.width_mm/1000, 3),
            'd': round(b.depth_mm/1000, 3),
            'l': round(b.length_mm/1000, 3),
        })
    
    columns = []
    for c in scene.columns.values():
        columns.append({
            'px': round(c.position.x/1000, 3),
            'pz': round(c.position.z/1000, 3),
            'w': round(c.width_mm/1000, 3),
            'd': round(c.depth_mm/1000, 3),
        })
    
    return {
        'walls': walls, 'rooms': rooms, 'furniture': furniture,
        'beams': beams, 'columns': columns,
        'doors': scene.door_count, 'windows': scene.window_count,
        'total_area': round(scene.total_floor_area_m2, 1),
    }