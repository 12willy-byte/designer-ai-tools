"""
施工图生成器
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene3d import Scene3D, OpeningType

def generate_door_window_schedule(scene):
    doors = []
    for i, op in enumerate(scene.doors.values(), 1):
        room_name = ""
        for wall in scene.walls.values():
            if op in wall.openings:
                for room in scene.rooms.values():
                    if wall.id in room.wall_ids:
                        room_name = room.name
                        break
                break
        doors.append({"seq": i, "code": f"M{i:04d}", "name": f"Door-{op.id[:6]}",
            "size": f"{op.width_mm:.0f}x{op.height_mm:.0f}",
            "count": 1, "material": "Solid wood door", "room": room_name})
    windows = []
    for i, op in enumerate(scene.windows.values(), 1):
        room_name = ""
        for wall in scene.walls.values():
            if op in wall.openings:
                for room in scene.rooms.values():
                    if wall.id in room.wall_ids:
                        room_name = room.name
                        break
                break
        windows.append({"seq": i, "code": f"C{i:04d}", "name": f"Window-{op.id[:6]}",
            "size": f"{op.width_mm:.0f}x{op.height_mm:.0f}",
            "count": 1, "sill_height": f"{op.sill_height_mm:.0f}",
            "material": "Aluminum alloy", "room": room_name})
    return {"project": scene.name, "doors": doors, "windows": windows,
            "door_count": len(doors), "window_count": len(windows)}

def generate_room_finish_schedule(scene):
    rooms_data = []
    style = scene.style or {}
    floor_default = style.get("floor_material", "Laminate")
    wall_default = style.get("wall_material", "Latex paint")
    for room in scene.rooms.values():
        area = room.area_m2
        perimeter = room.perimeter_mm / 1000
        ceiling_h = room.ceiling_height_mm / 1000
        wall_area = perimeter * ceiling_h
        opening_area = 0
        for wid in room.wall_ids:
            w = scene.walls.get(wid)
            if w:
                for op in w.openings:
                    opening_area += op.width_mm * op.height_mm / 1e6
        net_wall = max(0, wall_area - opening_area)
        rooms_data.append({"name": room.name, "floor_area_m2": round(area, 2),
            "perimeter_m": round(perimeter, 2), "wall_area_m2": round(net_wall, 2),
            "ceiling_area_m2": round(area, 2), "ceiling_height_m": round(ceiling_h, 2),
            "floor_material": floor_default, "wall_material": wall_default,
            "ceiling_material": "White ceiling", "requirements": room.requirements})
    return {"rooms": rooms_data, "room_count": len(rooms_data)}

def generate_material_annotation(scene):
    annotations = []
    for wall in scene.walls.values():
        mid_x = (wall.start.x + wall.end.x) / 2
        mid_z = (wall.start.z + wall.end.z) / 2
        annotations.append({"type": "wall", "id": wall.id[:8],
            "x": round(mid_x, 1), "z": round(mid_z, 1),
            "length_mm": round(wall.length_mm, 1),
            "thickness_mm": wall.thickness_mm, "openings": len(wall.openings)})
    for beam in scene.beams.values():
        annotations.append({"type": "beam", "id": beam.id[:8],
            "x": round(beam.position.x, 1), "z": round(beam.position.z, 1),
            "size": f"{beam.width_mm:.0f}x{beam.depth_mm:.0f}"})
    for col in scene.columns.values():
        annotations.append({"type": "column", "id": col.id[:8],
            "x": round(col.position.x, 1), "z": round(col.position.z, 1),
            "size": f"{col.width_mm:.0f}x{col.depth_mm:.0f}"})
    return {"annotations": annotations, "total": len(annotations)}

def generate_construction_docs(scene):
    return {
        "door_window": generate_door_window_schedule(scene),
        "room_finish": generate_room_finish_schedule(scene),
        "material_annotation": generate_material_annotation(scene),
        "quantities_summary": {
            "floor_area": round(scene.total_floor_area_m2, 2),
            "wall_area": round(scene.total_wall_area_m2, 2),
            "ceiling_area": round(scene.total_ceiling_area_m2, 2),
            "room_count": scene.room_count,
            "door_count": scene.door_count,
            "window_count": scene.window_count,
        }}
