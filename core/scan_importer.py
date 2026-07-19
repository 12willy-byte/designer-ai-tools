"""LiDAR/scan import helpers.

This module intentionally avoids pretending that every 3D file can be fully
understood. Semantic JSON exports can produce useful space facts; generic mesh
files produce a low-confidence summary and a confirmation checklist.
"""
import json
import os


SCHEMA_VERSION = "scan_summary.v1"
SEMANTIC_JSON_FORMATS = {".json", ".roomplan"}
MESH_FORMATS = {".usdz", ".usd", ".obj", ".glb", ".gltf", ".ply", ".stl"}


def summarize_scan_file(scan_path, metadata=None):
    """Return a scan summary suitable for Space Profile ingestion."""
    metadata = metadata or {}
    ext = os.path.splitext(scan_path)[1].lower()
    base = {
        "schema_version": SCHEMA_VERSION,
        "source": scan_path,
        "format": ext.lstrip(".") or "unknown",
        "file_size_bytes": os.path.getsize(scan_path) if os.path.exists(scan_path) else 0,
        "source_type": "unknown_scan",
        "confidence": 0.25,
        "rooms": [],
        "openings": [],
        "objects": [],
        "bounds_mm": None,
        "observations": [],
        "limitations": [],
        "metadata": metadata,
    }

    if ext in SEMANTIC_JSON_FORMATS:
        return _summarize_semantic_json(scan_path, base)
    if ext in MESH_FORMATS:
        base["source_type"] = "generic_mesh"
        base["observations"].append("已接收3D扫描/建模文件，但当前只能确认文件存在和格式。")
        base["limitations"].append("普通网格文件缺少墙、门、窗、房间用途等语义，需要解析器或人工标注。")
        base["limitations"].append("不能从普通网格文件可靠判断承重墙、管井、烟道和水电条件。")
        return base

    base["limitations"].append("暂不支持该扫描文件格式，需要先转成语义JSON、USDZ、OBJ、GLB、PLY或CAD/DXF。")
    return base


def _summarize_semantic_json(scan_path, base):
    with open(scan_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    rooms = _normalize_rooms(payload.get("rooms") or payload.get("spaces") or [])
    openings = _normalize_openings(payload.get("openings") or payload.get("doors_windows") or [])
    objects = payload.get("objects") or payload.get("furniture") or []

    summary = dict(base)
    summary.update({
        "source_type": payload.get("source_type") or "semantic_scan",
        "confidence": _num(payload.get("confidence")) or 0.68,
        "rooms": rooms,
        "openings": openings,
        "objects": objects,
        "bounds_mm": payload.get("bounds_mm") or payload.get("bounds"),
    })

    if rooms:
        summary["observations"].append(f"扫描数据包含 {len(rooms)} 个空间/房间。")
    if openings:
        summary["observations"].append(f"扫描数据包含 {len(openings)} 个门窗/开口。")
    if not rooms:
        summary["limitations"].append("语义扫描文件未提供房间列表。")
    if not openings:
        summary["limitations"].append("语义扫描文件未提供门窗/开口信息。")
    summary["limitations"].append("扫描数据仍需 CAD 或人工确认承重、水电、烟道和物业限制。")
    return summary


def _normalize_rooms(rooms):
    result = []
    for room in rooms:
        if not isinstance(room, dict):
            continue
        width = _num(room.get("width_mm") or room.get("width"))
        length = _num(room.get("length_mm") or room.get("depth_mm") or room.get("length"))
        area = _num(room.get("area_m2") or room.get("area"))
        if not area and width and length:
            area = width * length / 1_000_000
        result.append({
            "name": room.get("name") or room.get("label") or "",
            "area_m2": round(area, 2),
            "width_mm": int(width or 0),
            "length_mm": int(length or 0),
            "ceiling_height_mm": int(_num(room.get("ceiling_height_mm") or room.get("height_mm")) or 0),
            "orientation": room.get("orientation", ""),
            "adjacent_to": room.get("adjacent_to", []),
            "confidence": _num(room.get("confidence")) or 0.65,
        })
    return [room for room in result if room["name"]]


def _normalize_openings(openings):
    result = []
    for item in openings:
        if not isinstance(item, dict):
            continue
        result.append({
            "type": item.get("type") or "opening",
            "room": item.get("room", ""),
            "width_mm": int(_num(item.get("width_mm") or item.get("width")) or 0),
            "height_mm": int(_num(item.get("height_mm") or item.get("height")) or 0),
            "orientation": item.get("orientation", ""),
            "connects_to": item.get("connects_to", ""),
            "confidence": _num(item.get("confidence")) or 0.6,
        })
    return result


def _num(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("㎡", "").replace("m2", "").strip())
    except ValueError:
        return 0
