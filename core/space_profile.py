"""Space-object profile helpers for the automated design pipeline.

The profile is the stable handoff between raw inputs (survey, CAD, scan,
manual room data) and downstream design automation modules.
"""
import json
import os

from core.design_schema import normalize_conditions


SCHEMA_VERSION = "space_profile.v1"


def build_space_profile(conditions, cad_plan=None, scan_summary=None, source_files=None):
    """Build a verifiable profile of the space being designed."""
    normalized = normalize_conditions(conditions or {})
    space_data = normalized.get("space_data") or {}
    project = normalized.get("project") or {}
    rooms = _normalize_profile_rooms(space_data.get("rooms") or normalized.get("rooms") or [])
    if scan_summary and scan_summary.get("rooms"):
        rooms = _merge_rooms(rooms, _normalize_profile_rooms(scan_summary.get("rooms") or []))

    evidence = [{"type": "design_conditions", "confidence": 0.65}]
    geometry = {
        "source_type": "manual",
        "confidence": 0.45,
        "bounds_mm": None,
        "rooms": rooms,
        "doors": [],
        "windows": [],
        "notes": [],
    }

    if cad_plan:
        geometry = _merge_cad_geometry(geometry, cad_plan)
        evidence.append({"type": "cad_dxf", "confidence": 0.6, "source": cad_plan.get("source", "")})

    if scan_summary:
        geometry = _merge_scan_geometry(geometry, scan_summary, bool(cad_plan))
        evidence.append({
            "type": "scan",
            "confidence": _num(scan_summary.get("confidence")) or 0.55,
            "source": scan_summary.get("source", ""),
        })

    constraints = _collect_constraints(normalized)
    profile = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "name": project.get("name", ""),
            "address": project.get("address", ""),
            "house_type": project.get("house_type", ""),
            "area_m2": _num(project.get("area_m2") or space_data.get("total_area_m2")),
            "design_type": project.get("design_type", ""),
        },
        "design_object": {
            "category": "interior_space",
            "scope": project.get("design_type") or "concept_design",
            "description": _describe_object(project, rooms),
        },
        "geometry": geometry,
        "constraints": constraints,
        "evidence": evidence,
        "source_files": source_files or {},
    }
    profile["readiness"] = evaluate_space_profile(profile)
    profile["observations"] = build_space_observations(profile)
    profile["questions_to_confirm"] = build_space_questions(profile)
    return profile


def build_space_profile_from_file(conditions_json_path, cad_plan=None, scan_summary=None, output_path=None):
    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    profile = build_space_profile(conditions, cad_plan=cad_plan, scan_summary=scan_summary)
    if output_path:
        save_space_profile(profile, output_path)
    return profile


def save_space_profile(profile, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    return output_path


def build_space_cognition_package(conditions, output_dir, cad_plan=None, scan_summary=None, source_files=None):
    """Write the M0 space-cognition artifacts and return their paths."""
    os.makedirs(output_dir, exist_ok=True)
    profile = build_space_profile(
        conditions,
        cad_plan=cad_plan,
        scan_summary=scan_summary,
        source_files=source_files,
    )
    profile_path = save_space_profile(profile, os.path.join(output_dir, "space_profile.json"))

    cad_plan_path = None
    if cad_plan:
        cad_plan_path = os.path.join(output_dir, "cad_plan.json")
        with open(cad_plan_path, "w", encoding="utf-8") as f:
            json.dump(cad_plan, f, ensure_ascii=False, indent=2)

    scan_summary_path = None
    if scan_summary:
        scan_summary_path = os.path.join(output_dir, "scan_summary.json")
        with open(scan_summary_path, "w", encoding="utf-8") as f:
            json.dump(scan_summary, f, ensure_ascii=False, indent=2)

    observations_path = os.path.join(output_dir, "space_observations.json")
    with open(observations_path, "w", encoding="utf-8") as f:
        json.dump(profile["observations"], f, ensure_ascii=False, indent=2)

    questions_path = os.path.join(output_dir, "questions_to_confirm.json")
    with open(questions_path, "w", encoding="utf-8") as f:
        json.dump(profile["questions_to_confirm"], f, ensure_ascii=False, indent=2)

    return {
        "space_profile": profile_path,
        "cad_plan": cad_plan_path,
        "scan_summary": scan_summary_path,
        "space_observations": observations_path,
        "questions_to_confirm": questions_path,
        "profile": profile,
    }


def evaluate_space_profile(profile):
    """Return readiness gates for downstream automation."""
    project = profile.get("project") or {}
    geometry = profile.get("geometry") or {}
    rooms = geometry.get("rooms") or []
    blocking = []
    warnings = []
    unknowns = []

    if not project.get("house_type") and not project.get("design_type"):
        unknowns.append("缺少空间类型或设计类型")
    if not rooms:
        blocking.append("缺少房间/空间列表")
    if not any(_num(room.get("area_m2")) or (_num(room.get("width_mm")) and _num(room.get("length_mm"))) for room in rooms):
        blocking.append("缺少可计算面积或长宽尺寸")
    if not project.get("area_m2") and not sum(_num(room.get("area_m2")) for room in rooms):
        warnings.append("缺少总面积，后续预算和材料估算不可靠")
    if not geometry.get("doors"):
        unknowns.append("门洞位置未知，动线判断只能做概念级建议")
    if not geometry.get("windows"):
        unknowns.append("窗户/采光面未知，采光和色彩建议需要人工复核")

    confidence = _num(geometry.get("confidence"))
    if confidence < 0.5:
        warnings.append("空间几何置信度较低，建议人工确认后再进入自动布局")

    score = 100
    score -= len(blocking) * 30
    score -= len(warnings) * 12
    score -= len(unknowns) * 6
    score = max(0, min(100, score))

    ready_for = []
    if not blocking:
        ready_for.append("concept_package")
    if not blocking and confidence >= 0.6 and geometry.get("doors"):
        ready_for.append("layout_draft")
    if not blocking and project.get("area_m2"):
        ready_for.append("budget_estimate")

    return {
        "score": score,
        "ready_for": ready_for,
        "blocking_issues": blocking,
        "warnings": warnings,
        "unknowns": unknowns,
    }


def build_space_observations(profile):
    """Create design-facing observations from the space profile."""
    geometry = profile.get("geometry") or {}
    rooms = geometry.get("rooms") or []
    observations = []
    risks = []

    for room in rooms:
        name = room.get("name", "未命名空间")
        area = _num(room.get("area_m2"))
        orientation = room.get("orientation") or ""
        adjacent = room.get("adjacent_to") or []
        if area:
            observations.append({
                "scope": name,
                "type": "area",
                "text": f"{name}面积约 {round(area, 2)}㎡，可作为后续布局和预算估算依据。",
                "confidence": geometry.get("confidence", 0.45),
            })
        if orientation:
            observations.append({
                "scope": name,
                "type": "orientation",
                "text": f"{name}朝向为{orientation}，色彩和采光策略需要优先考虑该朝向。",
                "confidence": geometry.get("confidence", 0.45),
            })
        if adjacent:
            observations.append({
                "scope": name,
                "type": "adjacency",
                "text": f"{name}连接{', '.join(adjacent)}，可用于判断动线和功能关系。",
                "confidence": geometry.get("confidence", 0.45),
            })

    if not geometry.get("doors"):
        risks.append("门洞位置未知，自动布局阶段不能可靠判断动线入口。")
    if not geometry.get("windows"):
        risks.append("窗户位置未知，采光、通风和视觉焦点需要人工确认。")
    if not (profile.get("constraints") or {}).get("structural"):
        risks.append("承重墙/梁柱信息未确认，不允许自动给出拆改结论。")
    if geometry.get("source_type") in ("scan", "mixed"):
        risks.append("LiDAR/扫描数据反映现场现状，但不能单独证明承重、水电、烟道和物业限制。")

    return {
        "summary": _summarize_profile(profile),
        "observations": observations,
        "risks": risks,
    }


def build_space_questions(profile):
    """Turn unknowns and risks into a confirmation checklist."""
    readiness = profile.get("readiness") or {}
    constraints = profile.get("constraints") or {}
    questions = []

    for issue in readiness.get("blocking_issues", []):
        questions.append({
            "category": "blocking",
            "question": issue,
            "reason": "该信息缺失会阻断后续自动设计。",
            "required": True,
        })
    for unknown in readiness.get("unknowns", []):
        questions.append({
            "category": "space_unknown",
            "question": unknown,
            "reason": "该信息会影响空间判断准确性。",
            "required": False,
        })
    if not constraints.get("structural"):
        questions.append({
            "category": "structure",
            "question": "请确认承重墙、梁、柱、不可拆改边界。",
            "reason": "LiDAR 和普通房间数据无法可靠判断结构安全。",
            "required": True,
        })
    if not constraints.get("mep"):
        questions.append({
            "category": "mep",
            "question": "请确认管井、烟道、上下水、燃气和强弱电位置。",
            "reason": "这些约束决定厨房、卫生间和机电改造边界。",
            "required": True,
        })
    # 无名大环兜底提问（方案 d）：亲和度评分也未采纳的 ≥10㎡ 闭环不得静默
    # 无名——命名与提问两者必居其一。附最近未占用文字线索（若有）。
    geometry = profile.get("geometry") or {}
    for room in geometry.get("rooms") or []:
        name = room.get("name") or ""
        area = _num(room.get("area_m2")) or 0
        if not name.startswith("未命名空间") or area < 10:
            continue
        hint = room.get("naming_hint") or {}
        hint_text = hint.get("nearest_free_text")
        if hint_text:
            detail = (f"最相近的未占用房间名文字“{hint_text}”"
                      f"（距环边界约 {round((hint.get('dist_mm') or 0) / 1000, 1)}m，"
                      f"亲和度评分 {hint.get('affinity_score')} 未达采纳线）")
        else:
            detail = "图中没有可用的未占用房间名文字"
        questions.append({
            "category": "room_naming",
            "question": (f"{area}㎡ 空间疑似{hint_text or '功能房间'}？"
                         f"该闭环无环内房间名文字，{detail}。"),
            "reason": "大空间静默无名会使概念/布局/预算的分房间小计全部失真。",
            "required": False,
        })
    # 条带空间提问（方案三 d）：类型推断命中的环与有文字未成环的空间。
    for room in geometry.get("rooms") or []:
        if room.get("inferred_type"):
            questions.append({
                "category": "strip_space",
                "question": (f"{room.get('name')}（{_num(room.get('area_m2'))}㎡）"
                             f"疑似{room['inferred_type']}？系贴户型边缘+大开口形态的"
                             "位置推断（低置信），未自动改名。"),
                "reason": "条带空间类型影响功能定位与分房间小计。",
                "required": False,
            })
    for item in geometry.get("unformed_space_texts") or []:
        questions.append({
            "category": "strip_space",
            "question": (f"图中有“{item.get('text')}”文字但未识别到对应闭环空间"
                         "（可能两端开口未围合）。该空间是否存在？范围如何？"),
            "reason": "有文字未成的空间（多为走廊）缺失会使动线与面积账不实。",
            "required": False,
        })
    # 残环提问（方案四 d）：partial 环面积疑似缩水，附满框对比。
    for room in geometry.get("rooms") or []:
        if not room.get("partial"):
            continue
        bbox_area = _num(room.get("partial_bbox_area_m2"))
        area = _num(room.get("area_m2"))
        compare = (f"满框约 {bbox_area}㎡ vs 实测 {area}㎡"
                   if bbox_area else f"实测 {area}㎡")
        questions.append({
            "category": "partial_room",
            "question": (f"{room.get('name')}疑似残环（{compare}）：边界不完整，"
                         "实际范围是否更大？缺失边在哪一侧？"),
            "reason": "残环会使该房间工程量与家具布置建立在缩水事实上。",
            "required": False,
        })
    return questions


def _normalize_profile_rooms(rooms):
    result = []
    for room in rooms:
        if isinstance(room, str):
            result.append({"name": room, "area_m2": 0, "width_mm": 0, "length_mm": 0, "requirements": {}})
            continue
        if not isinstance(room, dict):
            continue
        width = _num(room.get("width_mm") or room.get("width"))
        length = _num(room.get("length_mm") or room.get("height_mm") or room.get("length") or room.get("height"))
        area = _num(room.get("area_m2") or room.get("area"))
        if not area and width and length:
            area = width * length / 1_000_000
        result.append({
            "name": room.get("name", ""),
            "area_m2": round(area, 2),
            "width_mm": int(width or 0),
            "length_mm": int(length or 0),
            "orientation": room.get("orientation", ""),
            "adjacent_to": room.get("adjacent_to", []),
            "requirements": room.get("requirements") or {},
            "floor_points": room.get("floor_points") or [],
            "source": room.get("source", ""),
            "perimeter_m": _num(room.get("perimeter_m")),
            # 层高是 M5 预算工程量（墙面/顶面面积）的事实依据；输入未给时为 0，
            # 下游按基准表默认值估算并标注假设。
            "ceiling_height_mm": int(_num(room.get("ceiling_height_mm")) or 0),
        })
        # 解析侧命名留痕（亲和度评分未采纳的线索）仅当存在时透传，
        # 供 build_space_questions 生成"疑似XX？"待确认问题，不影响既有字段。
        if room.get("naming_hint"):
            result[-1]["naming_hint"] = room["naming_hint"]
    return [room for room in result if room.get("name")]


def _merge_rooms(base_rooms, evidence_rooms):
    by_name = {room.get("name"): dict(room) for room in base_rooms if room.get("name")}
    for room in evidence_rooms:
        name = room.get("name")
        if not name:
            continue
        current = by_name.get(name, {})
        merged = dict(current)
        for key, value in room.items():
            if value not in (None, "", [], {}) and not merged.get(key):
                merged[key] = value
        by_name[name] = merged
    return list(by_name.values())


def _merge_cad_geometry(geometry, cad_plan):
    merged = dict(geometry)
    # 矢量 PDF 解析结果与 cad_plan 同构，走同一融合通道；
    # source_type 由解析方标注（cad_reader 不标注，默认 cad）。
    merged["source_type"] = cad_plan.get("source_type") or "cad"
    detected_rooms = _cad_rooms_to_profile_rooms(cad_plan)
    if detected_rooms:
        merged["rooms"] = _merge_rooms(
            _normalize_profile_rooms(merged.get("rooms") or []),
            detected_rooms,
        )
    base_confidence = 0.68 if detected_rooms else 0.6
    if cad_plan.get("doors") and cad_plan.get("windows"):
        base_confidence = max(base_confidence, 0.72)
    merged["confidence"] = max(_num(merged.get("confidence")), base_confidence)
    # 解析方自带置信度（如 PDF 比例尺未校准时 0.25）时向下封顶，
    # 避免低置信几何被闸门当作高置信事实放行。
    if cad_plan.get("confidence") is not None:
        merged["confidence"] = min(merged["confidence"], _num(cad_plan.get("confidence")))
    for limitation in cad_plan.get("limitations") or []:
        merged["notes"] = list(merged.get("notes") or []) + [limitation]
    bounds = cad_plan.get("bounds")
    if bounds:
        merged["bounds_mm"] = {
            "min_x": bounds[0],
            "min_y": bounds[1],
            "max_x": bounds[2],
            "max_y": bounds[3],
        }
    merged["doors"] = _door_items(cad_plan)
    merged["windows"] = _segments_to_items(cad_plan.get("windows") or [])
    # 未成环的"阳台/走廊"文字留痕透传（方案三 d 提问依据）。
    if cad_plan.get("unformed_space_texts"):
        merged["unformed_space_texts"] = cad_plan["unformed_space_texts"]
    if cad_plan.get("total_lines"):
        merged["notes"] = list(merged.get("notes") or []) + [f"CAD识别到 {cad_plan['total_lines']} 条线段"]
    if detected_rooms:
        merged["notes"] = list(merged.get("notes") or []) + [f"CAD识别到 {len(detected_rooms)} 个疑似空间闭环"]
    merged["cad_summary"] = {
        "source": cad_plan.get("source", ""),
        "layer_count": len(cad_plan.get("layers") or []),
        "wall_count": cad_plan.get("wall_count", len(cad_plan.get("walls") or [])),
        "door_count": cad_plan.get("door_count", len(cad_plan.get("doors") or [])),
        "window_count": cad_plan.get("window_count", len(cad_plan.get("windows") or [])),
        "detected_room_count": len(detected_rooms),
    }
    return merged


def _cad_rooms_to_profile_rooms(cad_plan):
    rooms = []
    for idx, room in enumerate(cad_plan.get("detected_rooms") or []):
        points = room.get("floor_points") or []
        xs = [_num(p.get("x")) for p in points if isinstance(p, dict)]
        ys = [_num(p.get("y")) for p in points if isinstance(p, dict)]
        width = max(xs) - min(xs) if xs else 0
        length = max(ys) - min(ys) if ys else 0
        item = {
            "name": room.get("name") or f"CAD识别空间{idx + 1}",
            "area_m2": _num(room.get("area_m2")),
            "width_mm": int(width or 0),
            "length_mm": int(length or 0),
            "floor_points": points,
            "perimeter_m": _num(room.get("perimeter_m")),
            # 双图融合的房间自带来源标记（structure/merged/plan_only），
            # 优先沿用；单图路径行为不变。
            "source": room.get("source") or cad_plan.get("source_type") or "cad_dxf",
        }
        # 融合房间自带置信度（双源一致升档/plan_only 降档）时透传给下游。
        if room.get("confidence") is not None:
            item["confidence"] = _num(room.get("confidence"))
        if room.get("needs_site_verification"):
            item["needs_site_verification"] = True
        # 命名留痕（亲和度评分未采纳线索）透传，供 questions_to_confirm 提问。
        if room.get("naming_hint"):
            item["naming_hint"] = room["naming_hint"]
        # 条带空间留痕透传（方案三）：文字锚定豁免与类型推断只加字段。
        for key in ("strip_space", "space_kind", "net_width_mm",
                    "inferred_type", "inference_confidence"):
            if room.get(key) is not None:
                item[key] = room[key]
        # 残环标注透传（方案四）：partial 只降置信不改数据。
        if room.get("partial"):
            item["partial"] = True
            item["partial_reasons"] = room.get("partial_reasons") or []
            item["partial_bbox_area_m2"] = room.get("partial_bbox_area_m2")
        rooms.append(item)
    return rooms


def _merge_scan_geometry(geometry, scan_summary, has_cad):
    merged = dict(geometry)
    merged["source_type"] = "mixed" if has_cad else "scan"
    merged["confidence"] = max(_num(merged.get("confidence")), _num(scan_summary.get("confidence")) or 0.55)
    if scan_summary.get("bounds_mm"):
        merged["bounds_mm"] = scan_summary["bounds_mm"]
    if scan_summary.get("rooms"):
        merged["rooms"] = _merge_rooms(
            _normalize_profile_rooms(merged.get("rooms") or []),
            _normalize_profile_rooms(scan_summary.get("rooms") or []),
        )
    openings = scan_summary.get("openings") or []
    doors = [item for item in openings if item.get("type") == "door"]
    windows = [item for item in openings if item.get("type") == "window"]
    if doors:
        merged["doors"] = doors
    if windows:
        merged["windows"] = windows
    merged["scan_summary"] = {
        "source": scan_summary.get("source", ""),
        "format": scan_summary.get("format", ""),
        "source_type": scan_summary.get("source_type", ""),
        "confidence": scan_summary.get("confidence", 0),
    }
    return merged


def _segments_to_items(segments):
    items = []
    for seg in segments:
        if len(seg) >= 4:
            items.append({"start": [seg[0], seg[1]], "end": [seg[2], seg[3]]})
    return items


def _door_items(cad_plan):
    """门条目：有 door_details（PDF 单图语义分级/双图融合）时透传
    宽度、连通房间、类型与置信度；否则退化为纯线段（原行为）。"""
    details = cad_plan.get("door_details") or []
    if details:
        items = []
        for det in details:
            item = {
                "start": det.get("start"),
                "end": det.get("end"),
                "door_type": det.get("type"),
                "confidence": det.get("confidence"),
                "source": det.get("source") or cad_plan.get("source_type"),
            }
            if det.get("width_mm") is not None:
                item["width_mm"] = det.get("width_mm")
            if det.get("connects"):
                item["connects_to"] = det.get("connects")
            if det.get("needs_site_verification"):
                item["needs_site_verification"] = True
            if det.get("note"):
                item["note"] = det.get("note")
            items.append(item)
        return items
    return _segments_to_items(cad_plan.get("doors") or [])


def _collect_constraints(conditions):
    special = conditions.get("special_requirements") or {}
    constraints = {
        "structural": [],
        "mep": [],
        "budget": conditions.get("budget") or {},
        "unknowns": [],
    }
    for key, value in special.items():
        text = f"{key}: {value}"
        if any(word in str(key) for word in ("承重", "梁", "柱", "结构")):
            constraints["structural"].append(text)
        elif any(word in str(key) for word in ("水", "电", "燃气", "烟道", "管井")):
            constraints["mep"].append(text)
        else:
            constraints["unknowns"].append(text)
    return constraints


def _describe_object(project, rooms):
    house_type = project.get("house_type") or "未知空间"
    area = project.get("area_m2")
    room_names = "、".join(room.get("name", "") for room in rooms[:6] if room.get("name"))
    area_text = f"{area}㎡" if area else "面积未知"
    return f"{house_type}，{area_text}，包含：{room_names or '空间清单未知'}"


def _summarize_profile(profile):
    project = profile.get("project") or {}
    geometry = profile.get("geometry") or {}
    rooms = geometry.get("rooms") or []
    return {
        "design_object": (profile.get("design_object") or {}).get("description", ""),
        "room_count": len(rooms),
        "known_area_m2": project.get("area_m2") or round(sum(_num(room.get("area_m2")) for room in rooms), 2),
        "geometry_source": geometry.get("source_type", ""),
        "geometry_confidence": geometry.get("confidence", 0),
        "readiness_score": (profile.get("readiness") or {}).get("score", 0),
    }


def _num(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("㎡", "").replace("m2", "").strip())
    except ValueError:
        return 0
