"""Helpers for normalizing design-condition JSON across MVP modules."""


def normalize_conditions(conditions):
    """Return a copy with stable keys expected by concept-design steps."""
    normalized = dict(conditions or {})
    rooms = _normalize_rooms(normalized)
    normalized["rooms"] = rooms
    normalized["rooms_requirements"] = _normalize_room_requirements(normalized, rooms)
    normalized["space_data"] = _normalize_space_data(normalized, rooms)
    return normalized


def _normalize_rooms(conditions):
    rooms = conditions.get("rooms") or []
    if isinstance(rooms, dict):
        return [{"name": name, "requirements": req or {}} for name, req in rooms.items()]
    normalized = []
    for room in rooms:
        if isinstance(room, str):
            normalized.append({"name": room, "requirements": {}})
        elif isinstance(room, dict):
            normalized.append(dict(room))
    return normalized


def _normalize_room_requirements(conditions, rooms):
    reqs = conditions.get("rooms_requirements")
    if isinstance(reqs, dict):
        return reqs
    result = {}
    for room in rooms:
        name = room.get("name", "")
        if not name:
            continue
        requirements = room.get("requirements") or {}
        if isinstance(requirements, dict):
            result[name] = requirements
        else:
            result[name] = {"notes": str(requirements)}
    return result


def _normalize_space_data(conditions, rooms):
    space = dict(conditions.get("space_data") or {})
    if space.get("rooms"):
        # 用户直接提供 space_data.rooms 时,补齐下游步骤依赖的 width_mm/height_mm/area_m2
        # (height_mm 在此约定为房间进深,与下方 derived_rooms 分支一致)
        normalized_space_rooms = []
        for room in space["rooms"]:
            if not isinstance(room, dict):
                continue
            entry = dict(room)
            width = _num(entry.get("width_mm") or entry.get("width") or entry.get("w"))
            height = _num(entry.get("height_mm") or entry.get("length_mm") or entry.get("length") or entry.get("depth_mm") or entry.get("h"))
            area = _num(entry.get("area_m2") or entry.get("area"))
            if not area and width and height:
                area = width * height / 1_000_000
            entry["width_mm"] = int(width or 0)
            entry["height_mm"] = int(height or 0)
            entry["area_m2"] = round(area or 0, 2)
            normalized_space_rooms.append(entry)
        space["rooms"] = normalized_space_rooms
        space["total_rooms"] = space.get("total_rooms") or len(normalized_space_rooms)
        space["total_area_m2"] = space.get("total_area_m2") or round(sum(r["area_m2"] for r in normalized_space_rooms), 2)
        return space

    derived_rooms = []
    for room in rooms:
        name = room.get("name", "")
        if not name:
            continue
        width = _num(room.get("width_mm") or room.get("width") or room.get("w"))
        height = _num(room.get("height_mm") or room.get("length_mm") or room.get("length") or room.get("h"))
        area = _num(room.get("area_m2") or room.get("area"))
        if not area and width and height:
            area = width * height / 1_000_000
        derived_rooms.append({
            "name": name,
            "width_mm": int(width or 0),
            "height_mm": int(height or 0),
            "area_m2": round(area or 0, 2),
        })

    total_area = sum(r["area_m2"] for r in derived_rooms)
    space.update({
        "rooms": derived_rooms,
        "total_rooms": len(derived_rooms),
        "total_area_m2": round(total_area, 2),
        "has_beams": bool(space.get("has_beams", False)),
        "has_columns": bool(space.get("has_columns", False)),
    })
    return space


def _num(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("m2", "").replace("㎡", "").strip())
    except ValueError:
        return 0
