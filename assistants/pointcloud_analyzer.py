"""
点云空间分析器 - RoomPlan/3D扫描到精确几何数据
路线二: 处理 RoomPlan LiDAR 数据提取精确尺寸
配合 spatial_vision 实现"语义+几何"双通道空间理解
"""
import os, sys, json, math
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def analyze_roomplan(roomplan_path):
    """
    解析 RoomPlan JSON，提取精确几何数据
    
    RoomPlan 数据结构:
    - surfaces: [{identifier, category(wall/door/window/floor/beam/column), 
                   dimensions:{x,y}, transform:[4x4 matrix], parentIdentifier}]
    - rooms: [{displayName, dimensions:{x,y}, surfaces:[identifier]}]
    
    返回归一化的空间几何数据
    """
    with open(roomplan_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    surfaces = data.get("surfaces", [])
    rooms_raw = data.get("rooms", [])
    
    smap = {s["identifier"]: s for s in surfaces}

    # 分类表面
    walls = [s for s in surfaces if s["category"] == "wall"]
    doors = [s for s in surfaces if s["category"] == "door"]
    windows = [s for s in surfaces if s["category"] == "window"]
    floors = [s for s in surfaces if s["category"] == "floor"]
    beams = [s for s in surfaces if s["category"] == "beam"]
    columns = [s for s in surfaces if s["category"] == "column"]

    # 计算变换矩阵中点的世界坐标
    def tform_point(m, x, y, z):
        return np.array([
            m[0]*x + m[4]*y + m[8]*z + m[12],
            m[1]*x + m[5]*y + m[9]*z + m[13],
            m[2]*x + m[6]*y + m[10]*z + m[14]
        ])

    # 墙端点
    wall_segments = []
    for w in walls:
        m = w["transform"]
        length = w["dimensions"]["x"]
        height = w["dimensions"]["y"]
        p1 = tform_point(m, 0, 0, 0)
        p2 = tform_point(m, length, 0, 0)
        wall_segments.append({
            "id": w["identifier"],
            "start": p1.tolist(),
            "end": p2.tolist(),
            "length_mm": length,
            "height_mm": height,
            "openings": [],
        })

    # 开口(门窗)关联到墙
    for door in doors:
        pid = door.get("parentIdentifier")
        if pid:
            for ws in wall_segments:
                if ws["id"] == pid:
                    m = door["transform"]
                    pos = tform_point(m, 0, 0, 0)
                    wm = smap[pid]["transform"]
                    w0 = tform_point(wm, 0, 0, 0)
                    wx = np.array([wm[0], wm[1], wm[2]])
                    wx_norm = np.linalg.norm(wx) or 1
                    offset = float(np.dot(pos - w0, wx / wx_norm))
                    ws["openings"].append({
                        "type": "door",
                        "offset_mm": round(offset, 1),
                        "width_mm": door["dimensions"]["x"],
                        "height_mm": door["dimensions"]["y"],
                    })
                    break

    for win in windows:
        pid = win.get("parentIdentifier")
        if pid:
            for ws in wall_segments:
                if ws["id"] == pid:
                    m = win["transform"]
                    pos = tform_point(m, 0, 0, 0)
                    wm = smap[pid]["transform"]
                    w0 = tform_point(wm, 0, 0, 0)
                    wx = np.array([wm[0], wm[1], wm[2]])
                    wx_norm = np.linalg.norm(wx) or 1
                    offset = float(np.dot(pos - w0, wx / wx_norm))
                    ws["openings"].append({
                        "type": "window",
                        "offset_mm": round(offset, 1),
                        "width_mm": win["dimensions"]["x"],
                        "height_mm": win["dimensions"]["y"],
                        "sill_height_mm": round(pos[1], 1),
                    })
                    break

    # 房间数据
    rooms = []
    total_area = 0
    for rm in rooms_raw:
        dims = rm.get("dimensions", {})
        w = dims.get("x", 0)
        d = dims.get("y", 0)
        area = round(w * d / 1e6, 2)
        total_area += area
        room_walls = [s for s in rm.get("surfaces", []) if s in smap and smap[s]["category"] == "wall"]
        rooms.append({
            "name": rm.get("displayName", ""),
            "width_mm": w,
            "depth_mm": d,
            "height_mm": 2800,
            "area_m2": area,
            "wall_count": len(room_walls),
            "wall_ids": room_walls,
        })

    # 梁柱数据
    beam_data = []
    for b in beams:
        m = b["transform"]
        p = tform_point(m, 0, 0, 0)
        beam_data.append({
            "position_mm": [round(v, 1) for v in p.tolist()],
            "width_mm": b["dimensions"]["x"],
            "depth_mm": b["dimensions"]["y"],
        })

    column_data = []
    for c in columns:
        m = c["transform"]
        p = tform_point(m, 0, 0, 0)
        column_data.append({
            "position_mm": [round(v, 1) for v in p.tolist()],
            "width_mm": c["dimensions"]["x"],
            "depth_mm": c["dimensions"]["y"],
        })

    return {
        "source": "RoomPlan LiDAR",
        "file": roomplan_path,
        "rooms": rooms,
        "total_area_m2": round(total_area, 2),
        "walls": wall_segments,
        "doors": [{"id": d["identifier"], "width_mm": d["dimensions"]["x"], 
                    "height_mm": d["dimensions"]["y"]} for d in doors],
        "windows": [{"id": w["identifier"], "width_mm": w["dimensions"]["x"],
                      "height_mm": w["dimensions"]["y"]} for w in windows],
        "beams": beam_data,
        "columns": column_data,
        "has_beams": len(beams) > 0,
        "has_columns": len(columns) > 0,
        "wall_count": len(walls),
        "door_count": len(doors),
        "window_count": len(windows),
    }


def merge_with_vision(pointcloud_data, vision_data):
    """
    合并点云精确几何 + VLM 空间语义
    
    点云提供: 精确尺寸(mm级)、墙门窗位置、梁柱数据
    VLM 提供: 房间类型、材质、光照、风格
    """
    return {
        "rooms": pointcloud_data.get("rooms", []),
        "total_area_m2": pointcloud_data.get("total_area_m2", 0),
        "walls": pointcloud_data.get("walls", []),
        "doors": pointcloud_data.get("doors", []),
        "windows": pointcloud_data.get("windows", []),
        "beams": pointcloud_data.get("beams", []),
        "columns": pointcloud_data.get("columns", []),
        "has_beams": pointcloud_data.get("has_beams", False),
        "has_columns": pointcloud_data.get("has_columns", False),
        "materials_detected": vision_data.get("materials_detected", {}),
        "room_types_vlm": vision_data.get("room_type", ""),
        "natural_light": vision_data.get("natural_light", ""),
        "source": "PointCloud+Vision",
        "precision": "millimeter (LiDAR)",
    }


def estimate_from_pointcloud(pointcloud_data):
    """
    从点云数据估算工程量
    比 CAD 读取更精确（毫米级 LiDAR 数据）
    """
    rooms = pointcloud_data.get("rooms", [])
    if not rooms:
        return None

    total_floor = sum(r["area_m2"] for r in rooms)
    total_wall = sum(2 * (r["width_mm"] + r["depth_mm"]) / 1000 * 2.8 for r in rooms)
    
    # 扣除门窗
    door_area = pointcloud_data.get("door_count", 2) * 0.9 * 2.1
    window_area = pointcloud_data.get("window_count", 1) * 1.8 * 1.5
    total_wall = max(0, total_wall - door_area - window_area)

    return {
        "total_floor_m2": round(total_floor, 2),
        "total_wall_m2": round(total_wall, 2),
        "total_ceiling_m2": round(total_floor, 2),
        "door_area_m2": round(door_area, 2),
        "window_area_m2": round(window_area, 2),
        "room_count": len(rooms),
    }
