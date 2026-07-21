"""M4 layout draft generation.

Runs only after the M2 automation gate allows ``layout_draft``. The module is
deterministic-first: every geometry-driven decision (wall assignment, furniture
size caps, door/window clearance) is computed by rules from M0 space facts, so
the output is auditable and demo mode works fully offline. A real LLM, when
available, only enriches narrative text (room notes / circulation overview) and
can never invent rooms, furniture or dimensions.

Anti-hallucination contract (same as the M3 prompt hardening):
- rooms come only from the space profile; never invent new spaces;
- furniture sizes are clamped to room dimensions and every clamp is logged;
- every inference lands in ``assumptions`` and is prefixed with "假设：";
- area follows the input building area, never a fabricated number.
"""
import json
import math
import os

from core.ai_client import get_client
from core.automation_gate import explain_blocked_module, explain_degraded_module


SCHEMA_VERSION = "layout_draft.v1"

# Door swing / passage clearance added on top of the door leaf width.
DOOR_CLEARANCE_EXTRA_MM = 100
# Fixed furniture in front of a window must stay below the (assumed) sill.
WINDOW_SILL_ASSUMED_MM = 900
# Min comfortable main passage.
MAIN_PASSAGE_MM = 900

_WALL_LABELS = {
    "wall_s": "长墙一",
    "wall_n": "长墙二",
    "wall_e": "短墙三",
    "wall_w": "短墙四",
}
_ORIENTATION_TO_WALL = {"南": "wall_s", "北": "wall_n", "东": "wall_e", "西": "wall_w"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_layout_draft(space_profile, needs_profile, gate=None):
    """Build the M4 layout draft, or a blocked-status dict.

    ``gate`` should be the M2 automation gate dict; when provided and
    ``layout_draft`` is not allowed, the existing blocked shape is returned
    (same as the pipeline already writes). Without a gate, minimal fact
    requirements are still enforced so the module never fabricates a layout
    from insufficient data.
    """
    if gate is not None and "layout_draft" not in (gate.get("allowed") or []):
        return {
            "status": "blocked_by_automation_gate",
            "module": "layout_draft",
            "reasons": explain_blocked_module(gate, "layout_draft") or ["自动化闸门未放行布局草案"],
        }

    space_profile = space_profile or {}
    needs_profile = needs_profile or {}
    room_facts = extract_room_facts(space_profile, needs_profile)
    if not room_facts:
        return _blocked_insufficient("缺少房间/空间事实，无法生成布局草案")
    if not any(op["kind"] == "door" for room in room_facts for wall in room["walls"] for op in wall["openings"]):
        return _blocked_insufficient("缺少门洞位置事实，不能可靠判断入口与动线")

    draft = _build_deterministic_draft(space_profile, needs_profile, room_facts)

    # 降级模式（draft_degraded）：闸门标记或事实上无窗时，草案明确标注
    # "采光面未知"，不伪造朝向/窗位判断。缺门洞几何在上面已被拦截。
    degraded_info = explain_degraded_module(gate, "layout_draft") if gate else None
    has_windows = any(op["kind"] == "window"
                      for room in room_facts for wall in room["walls"]
                      for op in wall["openings"])
    if not has_windows:
        draft["layout_mode"] = "draft_degraded"
        draft["degraded_reasons"] = (degraded_info or {}).get("reasons") or [
            "缺少窗户/采光面位置"]
        draft["assumptions"].insert(0, _assumption(
            "采光面未知，本布局草案为降级模式（draft_degraded）：布局未考虑朝向与窗位，"
            "采光、通风与视觉焦点需人工补充窗户事实后重新深化，当前版本仅用于讨论"
            "空间关系与家具尺度。"))
    else:
        draft["layout_mode"] = "draft"

    client = get_client()
    if client.demo_mode:
        draft["demo"] = True
        draft["generation"] = {"mode": "rules_only_demo", "provider": client.provider, "warnings": []}
    else:
        warnings = []
        if client.available:
            try:
                _enrich_with_ai(client, draft, room_facts, needs_profile)
                mode = "rules_plus_ai"
            except Exception as exc:  # keep deterministic draft as safe fallback
                mode = "rules_only_fallback"
                warnings.append(f"AI 文字增强失败，已回退到规则草案：{type(exc).__name__}")
        else:
            mode = "rules_only_fallback"
            warnings.append("未配置 AI API Key，布局草案仅含规则引擎输出。")
        draft["demo"] = False
        draft["generation"] = {"mode": mode, "provider": client.provider, "warnings": warnings}

    return draft


def build_layout_draft_package(space_profile, needs_profile, gate=None, output_dir=None):
    """Build the draft and (when it is a real draft) write JSON + summary files."""
    draft = build_layout_draft(space_profile, needs_profile, gate=gate)
    artifacts = {"layout_draft": None, "layout_summary_md": None}
    if output_dir and draft.get("status") == "draft":
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, "layout_draft.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(draft, f, ensure_ascii=False, indent=2)
        md_path = os.path.join(output_dir, "layout_draft_summary.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(render_layout_summary(draft))
        artifacts = {"layout_draft": json_path, "layout_summary_md": md_path}
    draft["artifacts"] = artifacts
    return {"draft": draft, **artifacts}


def render_layout_summary(draft):
    """Human-readable markdown summary of the layout draft."""
    lines = ["# 布局草案摘要（M4，供设计师讨论与复核）", ""]
    if draft.get("layout_mode") == "draft_degraded":
        lines.append("> ⚠️ **降级模式（draft_degraded）**：采光面未知，布局未考虑朝向/窗位，"
                     "采光、通风与视觉焦点需人工补充窗户事实后重新深化。")
        for reason in draft.get("degraded_reasons") or []:
            lines.append("> - %s" % reason)
        lines.append("")
    facts = draft.get("source_facts") or {}
    project = draft.get("project") or {}
    lines.append(
        "项目：%s；几何来源：%s（置信度 %s）；房间 %d 个，门 %d 个，窗 %d 个。"
        % (
            project.get("name") or "未命名项目",
            facts.get("geometry_source") or "未知",
            facts.get("geometry_confidence"),
            facts.get("room_count", 0),
            facts.get("door_count", 0),
            facts.get("window_count", 0),
        )
    )
    lines.append("")
    for room in draft.get("rooms") or []:
        lines.append("## %s（%d×%d mm，约 %.1f㎡）" % (
            room.get("name", ""), room.get("width_mm", 0), room.get("length_mm", 0), room.get("area_m2", 0)))
        zones = "、".join(z.get("name", "") for z in room.get("zones") or [])
        lines.append("- 功能分区：%s" % (zones or "（无）"))
        for item in room.get("furniture") or []:
            req = "（响应需求：%s）" % item["from_requirement"] if item.get("from_requirement") else ""
            lines.append("- 家具：%s %d×%d mm，%s%s" % (
                item.get("item", ""), item.get("width_mm", 0), item.get("depth_mm", 0),
                item.get("placement", ""), req))
        for con in room.get("opening_constraints") or []:
            lines.append("- 门窗约束：%s → %s" % (con.get("fact", ""), con.get("rule", "")))
        lines.append("- 动线：%s" % (room.get("circulation") or "（无）"))
        if room.get("design_note"):
            lines.append("- 设计要点：%s" % room["design_note"])
        for point in room.get("confirm_points") or []:
            lines.append("- 现场确认：%s" % point)
        lines.append("")
    if draft.get("circulation_overview"):
        lines.append("## 整体动线")
        lines.append(draft["circulation_overview"])
        lines.append("")
    if draft.get("design_highlights"):
        lines.append("## 设计亮点")
        for item in draft["design_highlights"]:
            lines.append("- %s" % item)
        lines.append("")
    lines.append("## 假设与不确定项（须设计师复核）")
    for item in draft.get("assumptions") or []:
        lines.append("- %s" % item)
    lines.append("")
    return "\n".join(lines)


def furniture_fits_room(item, room):
    """Check a furniture item against room clear dimensions (either rotation)."""
    w = _num(item.get("width_mm"))
    d = _num(item.get("depth_mm"))
    rw = _num(room.get("width_mm"))
    rl = _num(room.get("length_mm"))
    if not (w and d and rw and rl):
        return True  # unknown dimensions cannot be disproved
    return (w <= rw and d <= rl) or (w <= rl and d <= rw)


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------

def extract_room_facts(space_profile, needs_profile):
    """Normalize rooms + door/window openings into per-room fact records."""
    geometry = (space_profile or {}).get("geometry") or {}
    rooms = geometry.get("rooms") or []
    requirements = _requirements_by_room(needs_profile)

    facts = []
    for room in rooms:
        name = room.get("name") or ""
        if not name:
            continue
        width = int(_num(room.get("width_mm")))
        length = int(_num(room.get("length_mm")))
        if not (width and length):
            continue  # without clear dimensions no safe layout is possible
        facts.append({
            "name": name,
            "area_m2": _num(room.get("area_m2")) or round(width * length / 1_000_000, 2),
            "width_mm": width,
            "length_mm": length,
            "orientation": room.get("orientation") or "",
            "adjacent_to": list(room.get("adjacent_to") or []),
            "requirements": requirements.get(name) or room.get("requirements") or {},
            "floor_points": room.get("floor_points") or [],
            "walls": _build_walls(width, length),
        })

    for kind, items in (("door", geometry.get("doors") or []), ("window", geometry.get("windows") or [])):
        for item in items:
            _attach_opening(facts, item, kind)
    return facts


def _build_walls(width_mm, length_mm):
    # Local wall frame: 长墙一/二 span the room width (开间), 短墙三/四 span the
    # length (进深). Directions are only attached when the input states them.
    return [
        {"id": "wall_s", "length_mm": width_mm, "direction": "", "openings": []},
        {"id": "wall_n", "length_mm": width_mm, "direction": "", "openings": []},
        {"id": "wall_e", "length_mm": length_mm, "direction": "", "openings": []},
        {"id": "wall_w", "length_mm": length_mm, "direction": "", "openings": []},
    ]


def _wall_label(wall):
    label = _WALL_LABELS[wall["id"]]
    if wall.get("direction"):
        label += "（朝%s）" % wall["direction"]
    return label


def _attach_opening(facts, item, kind):
    if not isinstance(item, dict):
        return
    # Scan-style opening: {"type", "room", "width_mm", "orientation", "connects_to"}
    if item.get("room"):
        room = next((r for r in facts if r["name"] == item.get("room")), None)
        if room is None:
            return
        orientation = (item.get("orientation") or "").strip()
        wall = _wall_by_id(room, _ORIENTATION_TO_WALL.get(orientation[:1]))
        if wall is None:
            wall = _widest_wall(room)
        if orientation and not wall.get("direction"):
            wall["direction"] = orientation[:1]
        wall["openings"].append({
            "kind": kind,
            "width_mm": int(_num(item.get("width_mm"))),
            "height_mm": int(_num(item.get("height_mm"))),
            "connects_to": item.get("connects_to") or "",
            "orientation": orientation,
            "span_mm": None,
            "door_type": item.get("door_type") or item.get("type"),
        })
        return
    # CAD-style segment: {"start": [x, y], "end": [x, y]}
    start, end = item.get("start"), item.get("end")
    if not (isinstance(start, (list, tuple)) and isinstance(end, (list, tuple)) and len(start) >= 2 and len(end) >= 2):
        return
    x1, y1, x2, y2 = (_num(start[0]), _num(start[1]), _num(end[0]), _num(end[1]))
    width = int(round(math.hypot(x2 - x1, y2 - y1)))
    if width <= 0:
        return
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    best = None  # (distance, room, wall_id, span)
    for room in facts:
        bbox = _room_bbox(room)
        if bbox is None:
            continue
        min_x, min_y, max_x, max_y = bbox
        candidates = [
            (abs(my - min_y), "wall_s", [min(x1, x2), max(x1, x2)]),
            (abs(my - max_y), "wall_n", [min(x1, x2), max(x1, x2)]),
            (abs(mx - max_x), "wall_e", [min(y1, y2), max(y1, y2)]),
            (abs(mx - min_x), "wall_w", [min(y1, y2), max(y1, y2)]),
        ]
        for dist, wall_id, span in candidates:
            if dist <= 250 and (best is None or dist < best[0]):
                best = (dist, room, wall_id, span)
    if best is None:
        return
    _, room, wall_id, span = best
    _wall_by_id(room, wall_id)["openings"].append({
        "kind": kind,
        "width_mm": width,
        "height_mm": 0,
        "connects_to": "",
        "orientation": "",
        "span_mm": [int(span[0]), int(span[1])],
        "door_type": item.get("door_type"),
    })


def _room_bbox(room):
    points = room.get("floor_points") or []
    xs = [_num(p.get("x")) for p in points if isinstance(p, dict)]
    ys = [_num(p.get("y")) for p in points if isinstance(p, dict)]
    xs = [x for x in xs if x or x == 0]
    ys = [y for y in ys if y or y == 0]
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _wall_by_id(room, wall_id):
    for wall in room["walls"]:
        if wall["id"] == wall_id:
            return wall
    return None


def _widest_wall(room):
    return max(room["walls"], key=lambda w: w["length_mm"])


def _requirements_by_room(needs_profile):
    result = {}
    for item in (needs_profile or {}).get("room_requirements") or []:
        name = item.get("room")
        if name:
            result[name] = item.get("requirements") or {}
    return result


# ---------------------------------------------------------------------------
# Deterministic draft
# ---------------------------------------------------------------------------

def _build_deterministic_draft(space_profile, needs_profile, room_facts):
    assumptions = []
    rooms = [_plan_room(room, assumptions) for room in room_facts]

    geometry = space_profile.get("geometry") or {}
    project = space_profile.get("project") or {}
    door_count = sum(1 for r in room_facts for w in r["walls"] for o in w["openings"] if o["kind"] == "door")
    window_count = sum(1 for r in room_facts for w in r["walls"] for o in w["openings"] if o["kind"] == "window")

    assumptions.append(_assumption(
        "门扇开启方向（左开/右开、内开/外开）未在输入中标明，布局按常规内开预估，现场确认后需微调家具定位。"))
    assumptions.append(_assumption(
        "窗台高度未提供，窗前固定家具避让按窗台不高于 %dmm 预估。" % WINDOW_SILL_ASSUMED_MM))
    assumptions.append(_assumption(
        "空间几何来自 %s（置信度 %s），施工与定制下单前必须现场复尺。"
        % (geometry.get("source_type") or "未知来源", geometry.get("confidence"))))
    if project.get("area_m2"):
        assumptions.append(_assumption(
            "面积口径以输入建筑面积 %s㎡ 为准；各房间尺寸来自空间事实，加总与建面差异属公摊/墙体口径差。"
            % project["area_m2"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "draft",
        "module": "layout_draft",
        "project": {
            "name": project.get("name", ""),
            "house_type": project.get("house_type", ""),
            "area_m2": project.get("area_m2"),
        },
        "source_facts": {
            "geometry_source": geometry.get("source_type", ""),
            "geometry_confidence": geometry.get("confidence"),
            "room_count": len(room_facts),
            "door_count": door_count,
            "window_count": window_count,
        },
        "rooms": rooms,
        "circulation_overview": _circulation_overview(room_facts),
        "design_highlights": _design_highlights(needs_profile),
        "assumptions": assumptions,
    }


def _plan_room(room, assumptions):
    rtype = _room_type(room)
    req_text = " ".join(str(v) for v in (room.get("requirements") or {}).values())

    furniture = _furniture_plan(rtype, room, req_text, assumptions)
    for item in furniture:
        _clamp_item(item, room, assumptions)

    return {
        "name": room["name"],
        "room_type": rtype,
        "area_m2": room["area_m2"],
        "width_mm": room["width_mm"],
        "length_mm": room["length_mm"],
        "orientation": room.get("orientation") or "",
        "zones": _zones_plan(rtype, room, req_text),
        "furniture": furniture,
        "opening_constraints": _opening_constraints(room),
        "circulation": _room_circulation(room),
        "confirm_points": _confirm_points(rtype, room, req_text),
    }


def _room_type(room):
    name = room["name"]
    req_text = " ".join(str(v) for v in (room.get("requirements") or {}).values())
    # Name decides the room type first; requirement keywords only refine
    # bedroom subtypes (e.g. 次卧 + 儿童 -> kids_room). A living room with
    # 亲子活动 needs must stay a living room.
    if "主卧" in name:
        return "master_bedroom"
    if any(k in name for k in ("次卧", "卧室", "客房", "老人房")):
        if "儿童" in name or "儿童" in req_text or "亲子" in req_text:
            return "kids_room"
        return "bedroom"
    if "书房" in name:
        return "study"
    if any(k in name for k in ("客厅", "起居室")):
        return "living"
    if "餐厅" in name:
        return "dining"
    if "厨" in name:
        return "kitchen"
    if any(k in name for k in ("卫生间", "浴室", "盥洗")):
        return "bathroom"
    if any(k in name for k in ("玄关", "门厅")):
        return "entry"
    if "阳台" in name:
        return "balcony"
    return "generic"


def _pick_wall(room, avoid=("door", "window"), exclude_ids=()):
    """Pick the longest wall free of the given opening kinds."""
    def _ok(w, avoid_kinds):
        return w["id"] not in exclude_ids and not any(o["kind"] in avoid_kinds for o in w["openings"])

    candidates = [w for w in room["walls"] if _ok(w, avoid)]
    if not candidates and "window" in avoid:
        candidates = [w for w in room["walls"] if _ok(w, ("door",))]
    if not candidates:
        candidates = [w for w in room["walls"] if w["id"] not in exclude_ids]
    if not candidates:
        candidates = list(room["walls"])
    return max(candidates, key=lambda w: w["length_mm"])


def _furniture_plan(rtype, room, req_text, assumptions):
    """Rule-based furniture list with sizes clamped to walls and room."""
    items = []

    def add(item, width, depth, wall, placement, from_requirement="", notes=""):
        width = min(int(width), max(600, wall["length_mm"] - 200)) if wall else int(width)
        items.append({
            "item": item,
            "width_mm": int(width),
            "depth_mm": int(depth),
            "against_wall": _wall_label(wall) if wall else "",
            "placement": placement,
            "from_requirement": from_requirement,
            "notes": notes,
        })

    if rtype == "living":
        sofa_wall = _pick_wall(room)
        tv_wall = _pick_wall(room, avoid=("door",), exclude_ids={sofa_wall["id"]})
        add("三人沙发", 2400, 950, sofa_wall,
            "靠%s居中，面向视听区" % _wall_label(sofa_wall))
        add("电视柜", 2200, 400, tv_wall,
            "靠%s，与沙发相对" % _wall_label(tv_wall))
        add("茶几", 1200, 600, None, "沙发与电视柜之间居中，四周保留通行净空")
        if "收纳" in req_text or "展示" in req_text:
            storage_wall = _pick_wall(room, exclude_ids={sofa_wall["id"], tv_wall["id"]})
            add("收纳展示柜", 1600, 350, storage_wall,
                "靠%s，避开门窗开启范围" % _wall_label(storage_wall),
                from_requirement=req_text[:40])
    elif rtype in ("master_bedroom", "bedroom", "kids_room"):
        bed_wall = _pick_wall(room)
        bed_w = 1800 if rtype == "master_bedroom" else (1200 if rtype == "kids_room" else 1500)
        add("双人床" if rtype == "master_bedroom" else "单人床", bed_w, 2000, bed_wall,
            "床头靠%s，不正对门" % _wall_label(bed_wall))
        add("床头柜", 500, 400, bed_wall, "床侧，靠%s" % _wall_label(bed_wall))
        wardrobe_wall = _pick_wall(room, exclude_ids={bed_wall["id"]})
        if "整墙衣柜" in req_text:
            add("整墙衣柜", wardrobe_wall["length_mm"] - 200, 600, wardrobe_wall,
                "沿%s通长布置，避开门扇开启范围" % _wall_label(wardrobe_wall),
                from_requirement="需要整墙衣柜",
                notes="长度按墙面净宽预留，需现场复尺")
        else:
            add("衣柜", 1600 if rtype != "kids_room" else 1200, 600, wardrobe_wall,
                "靠%s，避开门扇开启范围" % _wall_label(wardrobe_wall))
        if rtype == "kids_room" or "书桌" in req_text or "书房" in req_text or "学习" in req_text:
            desk_wall = _pick_wall(room, avoid=("door",), exclude_ids={bed_wall["id"], wardrobe_wall["id"]})
            add("书桌", 1200, 600, desk_wall, "靠%s，优先靠近采光面侧面" % _wall_label(desk_wall),
                from_requirement="兼顾学习/办公" if rtype == "kids_room" else "")
    elif rtype == "study":
        desk_wall = _pick_wall(room)
        add("书桌", 1400, 700, desk_wall, "靠%s，面向房间" % _wall_label(desk_wall))
        shelf_wall = _pick_wall(room, avoid=("door",))
        add("书柜", 1600, 350, shelf_wall, "靠%s" % _wall_label(shelf_wall))
    elif rtype == "kitchen":
        counter_wall = _pick_wall(room)
        add("整体橱柜（地柜+吊柜）", max(1800, counter_wall["length_mm"] - 900), 600, counter_wall,
            "沿%s一字排开，洗-切-炒顺序布置" % _wall_label(counter_wall),
            notes="吊柜底距台面约 700mm，需结合现场烟道位置")
        fridge_wall = _pick_wall(room, avoid=("door",), exclude_ids={counter_wall["id"]})
        add("冰箱位", 800, 700, fridge_wall, "靠%s，靠近入口与备餐区" % _wall_label(fridge_wall),
            notes="两侧及背部预留散热间隙")
        if "大单槽" in req_text:
            add("大单槽水槽", 800, 500, counter_wall, "嵌入地柜台面，靠近上下水点位",
                from_requirement="需要大单槽")
        if "洗碗机" in req_text:
            add("洗碗机位", 600, 600, counter_wall, "嵌入地柜，紧邻水槽以便接驳上下水",
                from_requirement="需要洗碗机",
                notes="需确认进水、排水与电源点位")
    elif rtype == "bathroom":
        vanity_wall = _pick_wall(room, avoid=("door",))
        add("浴室柜", 900, 550, vanity_wall, "靠%s，靠近上下水" % _wall_label(vanity_wall))
        add("马桶区", 800, 700, vanity_wall, "靠近坑位，两侧预留通行空间",
            notes="坑距需现场确认")
        shower_wall = _pick_wall(room, exclude_ids={vanity_wall["id"]})
        if "干湿分离" in req_text:
            add("淋浴区（隔断）", 1000, 1000, shower_wall,
                "靠%s转角布置玻璃隔断，实现干湿分离" % _wall_label(shower_wall),
                from_requirement="干湿分离",
                notes="隔断开门方向与挡水条位置需现场确认")
        else:
            add("淋浴区", 900, 900, shower_wall, "靠%s转角布置" % _wall_label(shower_wall))
    elif rtype == "dining":
        add("餐桌", 1400, 800, None, "居中布置，四周保留≥900mm 通行")
        sideboard_wall = _pick_wall(room)
        add("餐边柜", 1400, 400, sideboard_wall, "靠%s" % _wall_label(sideboard_wall))
    elif rtype == "entry":
        wall = _pick_wall(room, avoid=("door",))
        add("鞋柜", 1200, 350, wall, "靠%s，不压缩入户通道" % _wall_label(wall))
    elif rtype == "balcony":
        wall = _pick_wall(room)
        add("洗衣/储物区", 700, 700, wall, "靠%s一角" % _wall_label(wall),
            notes="上下水与防水需现场确认")
    else:
        wall = _pick_wall(room)
        add("收纳柜", 1200, 500, wall, "靠%s" % _wall_label(wall),
            notes="房间功能定位需与业主确认后细化")

    return items


def _zones_plan(rtype, room, req_text):
    presets = {
        "living": [("会客观影区", "以沙发-茶几-电视柜为核心"), ("通行区", "入口至各房间门洞之间保持连续通道")],
        "master_bedroom": [("睡眠区", "以床为核心，远离门洞"), ("衣物收纳区", "沿整墙衣柜一侧"), ("通行区", "门洞至床侧通道")],
        "bedroom": [("睡眠区", "以床为核心"), ("收纳区", "衣柜一侧"), ("通行区", "门洞至床侧通道")],
        "kids_room": [("睡眠区", "以床为核心，远离窗开启扇"), ("学习区", "书桌采光侧面"), ("收纳区", "衣柜一侧")],
        "study": [("办公学习区", "书桌为核心"), ("藏书收纳区", "书柜一侧")],
        "kitchen": [("洗切区", "水槽与备餐台面"), ("烹饪区", "灶具与烟道一侧"), ("储物设备区", "冰箱与高柜")],
        "bathroom": [("盥洗区", "浴室柜一侧"), ("如厕区", "马桶区"), ("淋浴区", "转角或尽端")],
        "dining": [("就餐区", "餐桌居中"), ("备餐收纳区", "餐边柜一侧")],
        "entry": [("换鞋收纳区", "鞋柜一侧"), ("通行区", "入户主通道")],
        "balcony": [("家政区", "洗衣/储物一角"), ("通行与晾晒区", "保持开启与晾晒空间")],
        "generic": [("主要功能区", "待与业主确认功能定位"), ("收纳区", "沿实墙"), ("通行区", "保持连续通道")],
    }
    zones = [{"name": n, "position": p} for n, p in presets.get(rtype, presets["generic"])]
    if rtype == "living" and ("亲子" in req_text or "儿童" in req_text):
        zones.insert(1, {"name": "亲子活动区", "position": "客厅中部留空，便于看护与活动"})
    return zones


def _opening_constraints(room):
    constraints = []
    for wall in room["walls"]:
        for op in wall["openings"]:
            label = _wall_label(wall)
            if op["kind"] == "door":
                connects = "，连通%s" % op["connects_to"] if op.get("connects_to") else ""
                constraints.append({
                    "type": "door",
                    "wall": label,
                    "fact": "门洞宽 %dmm（位于%s%s）" % (op["width_mm"], label, connects),
                    "rule": "门扇开启侧预留 ≥%dmm 净空，高柜与固定家具避让开启范围" % (op["width_mm"] + DOOR_CLEARANCE_EXTRA_MM),
                    "action": "avoid_door_swing",
                })
            elif op["kind"] == "window":
                orient = "，朝%s" % op["orientation"] if op.get("orientation") else ""
                constraints.append({
                    "type": "window",
                    "wall": label,
                    "fact": "窗宽 %dmm（位于%s%s）" % (op["width_mm"], label, orient),
                    "rule": "窗前不布置高于 %dmm 的固定家具，预留窗帘安装与通风开启空间" % WINDOW_SILL_ASSUMED_MM,
                    "action": "keep_window_clear",
                })
    return constraints


def _room_circulation(room):
    doors = [(w, o) for w in room["walls"] for o in w["openings"] if o["kind"] == "door"]
    adjacent = "、".join(room.get("adjacent_to") or [])
    if doors:
        wall, door = doors[0]
        connects = door.get("connects_to") or (adjacent or "相邻空间")
        text = "自%s（%s，门宽 %dmm）进入" % (connects, _wall_label(wall), door["width_mm"])
        if len(doors) > 1:
            others = "、".join(o.get("connects_to") or "相邻空间" for _, o in doors[1:])
            text += "，并连通%s" % others
        text += "；房内主通道按 ≥%dmm 预留，家具避让门扇开启范围。" % MAIN_PASSAGE_MM
        return text
    if adjacent:
        return "与%s相邻，入口位置未在事实中标注，主通道按 ≥%dmm 预留，需现场确认门洞。" % (adjacent, MAIN_PASSAGE_MM)
    return "入口位置未在事实中标注，主通道按 ≥%dmm 预留，需现场确认门洞。" % MAIN_PASSAGE_MM


def _confirm_points(rtype, room, req_text):
    points = []
    doors = [o for w in room["walls"] for o in w["openings"] if o["kind"] == "door"]
    windows = [o for w in room["walls"] for o in w["openings"] if o["kind"] == "window"]
    if doors:
        points.append("现场确认门扇开启方向（左开/右开、内开/外开），据此微调家具与柜体定位。")
    if windows:
        points.append("现场确认窗台高度与窗扇开启方式，复核窗前家具高度与窗帘做法。")
    points.append("现场复尺房间净尺寸与墙面平整度，确认后再下定制订单。")
    if rtype == "kitchen":
        points.append("确认上下水、燃气、烟道与插座点位，核对洗碗机/水槽接驳条件。")
    if rtype == "bathroom":
        points.append("确认马桶坑距、地漏与沉箱位置，核对淋浴隔断安装条件。")
    if "整墙衣柜" in req_text:
        points.append("确认整墙衣柜墙面的开关/插座/踢脚线位置，必要时移位避让。")
    if rtype == "kids_room":
        points.append("确认儿童安全防护：家具圆角、防倾倒固定与窗户限位器。")
    return points


def _circulation_overview(room_facts):
    entries = []
    for room in room_facts:
        doors = [o for w in room["walls"] for o in w["openings"] if o["kind"] == "door"]
        for door in doors[:1]:
            connects = door.get("connects_to") or "相邻空间"
            entries.append("%s（门宽 %dmm，连通%s）" % (room["name"], door["width_mm"], connects))
    if not entries:
        return ""
    return ("房间连通关系：" + "；".join(entries) +
            "。各房间主通道均按 ≥%dmm 预留，家具避让门扇开启范围。" % MAIN_PASSAGE_MM)


def _design_highlights(needs_profile):
    highlights = []
    for priority in (needs_profile or {}).get("priorities") or []:
        label = priority.get("label")
        reason = priority.get("reason")
        if label and reason:
            highlights.append("回应「%s」需求：%s" % (label, reason))
    highlights.append("全部家具尺寸按房间净尺寸校验，固定家具避让门窗开启范围。")
    return highlights[:5]


def _clamp_item(item, room, assumptions):
    if furniture_fits_room(item, room):
        return
    rw, rl = room["width_mm"], room["length_mm"]
    w, d = item["width_mm"], item["depth_mm"]
    factor = min(rw / max(w, 1), rl / max(d, 1), rl / max(w, 1), rw / max(d, 1), 1.0)
    new_w = max(300, int(w * factor // 50 * 50))
    new_d = max(300, int(d * factor // 50 * 50))
    item["width_mm"], item["depth_mm"] = new_w, new_d
    assumptions.append(_assumption(
        "%s的%s尺寸按房间净尺寸收窄为 %d×%dmm（原建议 %d×%dmm），需现场复尺确认。"
        % (room["name"], item["item"], new_w, new_d, w, d)))


# ---------------------------------------------------------------------------
# AI enrichment (real mode only; narrative only, no geometry decisions)
# ---------------------------------------------------------------------------

_ENRICH_SYSTEM_PROMPT = """你是资深室内设计师。下面是基于空间事实（房间尺寸/门窗位置/相邻关系）由规则引擎生成的布局草案 JSON。
请在不改变任何房间、家具名称与尺寸的前提下，只输出文字增强 JSON：
{
  "circulation_overview": "整体动线说明，≤120字，必须引用具体房间与门的连通关系",
  "design_highlights": ["结合业主需求的亮点，每条≤40字"],
  "room_notes": [{"name": "房间名（必须与输入完全一致）", "note": "该房间布局要点，≤80字，需引用门窗位置"}],
  "extra_assumptions": ["仅当引入了输入之外的推断时填写，且必须以\\"假设：\\"开头"]
}

【事实与假设边界 — 必须严格遵守】
1. 禁止新增、合并或删除房间；room_notes 的 name 必须逐字匹配输入房间名。
2. 禁止修改或新增家具与尺寸；禁止编造品牌与型号。
3. 必须利用输入中的门窗位置/宽度与业主需求，不得泛泛而谈。
4. 输入未直接给出的推断必须以"假设："开头，且只能放入 extra_assumptions。"""


def _enrich_with_ai(client, draft, room_facts, needs_profile):
    payload = {
        "rooms": [
            {
                "name": r["name"],
                "width_mm": r["width_mm"],
                "length_mm": r["length_mm"],
                "orientation": r.get("orientation") or "",
                "adjacent_to": r.get("adjacent_to") or [],
                "openings": [
                    {
                        "kind": o["kind"],
                        "width_mm": o["width_mm"],
                        "wall": _wall_label(w),
                        "connects_to": o.get("connects_to") or "",
                    }
                    for w in r["walls"] for o in w["openings"]
                ],
                "requirements": r.get("requirements") or {},
                "planned_furniture": [
                    {"item": f["item"], "width_mm": f["width_mm"], "depth_mm": f["depth_mm"], "placement": f["placement"]}
                    for room_draft in draft["rooms"] if room_draft["name"] == r["name"]
                    for f in room_draft["furniture"]
                ],
            }
            for r in room_facts
        ],
        "needs_priorities": (needs_profile or {}).get("priorities") or [],
        "style": (needs_profile or {}).get("style_preferences") or {},
    }
    result = client.chat_json(
        _ENRICH_SYSTEM_PROMPT,
        json.dumps(payload, ensure_ascii=False),
        temperature=0.4,
        max_tokens=2500,
    )
    if not isinstance(result, dict):
        return
    overview = str(result.get("circulation_overview") or "").strip()
    if overview:
        draft["circulation_overview"] = overview
    highlights = [str(h).strip() for h in result.get("design_highlights") or [] if str(h).strip()]
    if highlights:
        draft["design_highlights"] = highlights[:6]
    valid_names = {r["name"] for r in draft["rooms"]}
    for note in result.get("room_notes") or []:
        if not isinstance(note, dict):
            continue
        name = note.get("name")
        text = str(note.get("note") or "").strip()
        if name in valid_names and text:
            for room in draft["rooms"]:
                if room["name"] == name:
                    room["design_note"] = text
    for item in result.get("extra_assumptions") or []:
        text = _assumption(str(item).strip())
        if text and text not in draft["assumptions"]:
            draft["assumptions"].append(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blocked_insufficient(reason):
    return {
        "status": "blocked_insufficient_facts",
        "module": "layout_draft",
        "reasons": [reason],
    }


def _assumption(text):
    text = (text or "").strip()
    if not text:
        return ""
    if not text.startswith("假设："):
        text = "假设：" + text.lstrip("假设:")
    return text


def _num(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("㎡", "").replace("m2", "").strip())
    except ValueError:
        return 0
