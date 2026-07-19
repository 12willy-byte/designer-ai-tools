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
        space["total_rooms"] = space.get("total_rooms") or len(space["rooms"])
        space["total_area_m2"] = space.get("total_area_m2") or sum(r.get("area_m2", 0) for r in space["rooms"])
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
