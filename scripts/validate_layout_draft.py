"""Offline validation for the M4 layout draft module.

Covers:
A. Scan scenario (RoomPlan semantic template): gate allows layout_draft, the
   draft JSON is structurally complete, furniture fits room dimensions, needs
   (dishwasher / full-wall wardrobe) land in concrete rooms, assumptions are
   prefixed, and the demo pipeline writes layout_draft.json + summary + PPTX.
B. CAD scenario (single master bedroom with door/window geometry): geometric
   door-swing avoidance — the wardrobe must not sit on the door wall and an
   avoid_door_swing constraint must be recorded.
C. Blocked regression: without geometry facts the gate still blocks
   layout_draft and the pipeline writes a blocked layout JSON without
   fabricating a draft.

Run: AI_DEMO_MODE=1 python3 scripts/validate_layout_draft.py
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

os.environ["AI_DEMO_MODE"] = "1"


def _scan_conditions(path):
    data = {
        "project": {
            "name": "扫描样例两室一厅",
            "house_type": "两室一厅",
            "area_m2": 68,
            "design_type": "整屋自动化方案",
        },
        "family": {
            "residents": "3人(夫妻+1孩)",
            "work_from_home": "偶尔",
            "storage_need": "较高",
            "cooking_frequency": "高频中餐",
        },
        "style": {
            "primary_style": "现代简约",
            "color_tone": "暖白、原木色、低饱和蓝灰",
            "keywords": "通透 温润 收纳",
        },
        "rooms": [
            {"name": "客厅", "requirements": {"功能": "会客、观影、亲子活动"}},
            {"name": "主卧", "requirements": {"功能": "睡眠、衣物收纳", "备注": "需要整墙衣柜"}},
            {"name": "次卧", "requirements": {"功能": "儿童房,兼顾书房"}},
            {"name": "厨房", "requirements": {"功能": "高频中餐,需要大单槽和洗碗机位"}},
            {"name": "卫生间", "requirements": {"功能": "干湿分离"}},
        ],
        "budget": {"total_budget": 280000},
        "special_requirements": {
            "承重墙": "外墙及结构墙不可拆改，需保留",
            "上下水": "厨房与卫生间湿区位置不可移动",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _cad_bedroom_conditions(path):
    data = {
        "project": {"name": "CAD主卧样例", "house_type": "一居室住宅", "area_m2": 24},
        "family": {"residents": "2人", "storage_need": "较高", "cooking_frequency": "每周数次"},
        "style": {"primary_style": "现代简约", "keywords": "清爽 收纳"},
        "rooms": [
            {"name": "主卧", "requirements": {"功能": "睡眠、衣物收纳", "备注": "需要整墙衣柜"}},
        ],
        "budget": {"total_budget": 120000},
        "special_requirements": {
            "承重墙": "外墙及结构墙不可拆改，需保留",
            "上下水": "卫生间湿区位置不可移动",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _bedroom_dxf(path):
    """4400x4200 master bedroom: door 900mm on east edge, window 1800mm on north edge."""
    import ezdxf

    doc = ezdxf.new("R2010")
    for layer in ("墙体", "门", "窗", "房间标注"):
        if layer not in [item.dxf.name for item in doc.layers]:
            doc.layers.add(layer)
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (4400, 0), (4400, 4200), (0, 4200)],
        close=True,
        dxfattribs={"layer": "墙体"},
    )
    msp.add_line((4400, 1500), (4400, 2400), dxfattribs={"layer": "门"})
    msp.add_line((1300, 4200), (3100, 4200), dxfattribs={"layer": "窗"})
    msp.add_text("主卧", height=250, dxfattribs={"layer": "房间标注"}).set_placement((2200, 2100))
    doc.saveas(path)


def _fail(message):
    raise SystemExit("FAIL: " + message)


def _check_draft_common(draft, expected_rooms):
    if draft.get("status") != "draft":
        _fail("layout draft status should be 'draft', got %s" % draft.get("status"))
    if draft.get("schema_version") != "layout_draft.v1":
        _fail("layout draft schema_version mismatch")
    rooms = {room["name"]: room for room in draft.get("rooms") or []}
    for name in expected_rooms:
        if name not in rooms:
            _fail("draft missing room %s" % name)
    for name, room in rooms.items():
        if not room.get("zones"):
            _fail("room %s has no zones" % name)
        if not room.get("furniture"):
            _fail("room %s has no furniture" % name)
        if not (room.get("circulation") or "").strip():
            _fail("room %s has no circulation text" % name)
        if not room.get("confirm_points"):
            _fail("room %s has no confirm points" % name)
        for item in room["furniture"]:
            from core.layout_draft import furniture_fits_room
            if not furniture_fits_room(item, room):
                _fail("room %s furniture %s (%dx%d) exceeds room dims %dx%d" % (
                    name, item.get("item"), item.get("width_mm"), item.get("depth_mm"),
                    room.get("width_mm"), room.get("length_mm")))
    assumptions = draft.get("assumptions") or []
    if not assumptions:
        _fail("draft has no assumptions")
    for item in assumptions:
        if not str(item).startswith("假设："):
            _fail("assumption not prefixed with 假设：: %s" % item)
    return rooms


def scenario_scan(tmp):
    from core.scan_importer import summarize_scan_file
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    conditions_path = os.path.join(tmp, "scan_case", "design_conditions.json")
    os.makedirs(os.path.dirname(conditions_path), exist_ok=True)
    _scan_conditions(conditions_path)
    scan_path = os.path.join(tmp, "scan_case", "roomplan_scan.json")
    shutil.copy2(os.path.join(ROOT, "templates", "roomplan_scan.template.json"), scan_path)
    scan_summary = summarize_scan_file(scan_path)

    result = run_mvp_concept_package(conditions_path, scan_summary=scan_summary)
    if "layout_draft" not in result.get("allowed_modules", []):
        _fail("gate should allow layout_draft with scan facts")
    if not result.get("layout_draft_json") or not os.path.exists(result["layout_draft_json"]):
        _fail("pipeline did not write layout_draft.json")
    if not result.get("layout_draft_summary") or not os.path.exists(result["layout_draft_summary"]):
        _fail("pipeline did not write layout_draft_summary.md")
    if not os.path.exists(result["pptx"]) or os.path.getsize(result["pptx"]) < 10000:
        _fail("pipeline pptx missing or too small")

    with open(result["layout_draft_json"], "r", encoding="utf-8") as f:
        draft = json.load(f)
    rooms = _check_draft_common(draft, ["客厅", "主卧", "次卧", "厨房", "卫生间"])

    # needs integration: dishwasher must land in the kitchen
    kitchen_items = " ".join(f.get("item", "") for f in rooms["厨房"]["furniture"])
    if "洗碗机" not in kitchen_items:
        _fail("kitchen furniture should include a dishwasher slot from needs")
    # room typing: living room with 亲子 needs must stay a living room
    living_items = " ".join(f.get("item", "") for f in rooms["客厅"]["furniture"])
    if "沙发" not in living_items:
        _fail("living room should include a sofa, got: %s" % living_items)
    if "床" in living_items:
        _fail("living room must not get bedroom furniture: %s" % living_items)
    # needs integration: full-wall wardrobe in master bedroom
    wardrobe = next((f for f in rooms["主卧"]["furniture"] if "衣柜" in f.get("item", "")), None)
    if wardrobe is None:
        _fail("master bedroom should include a wardrobe")
    if wardrobe["width_mm"] < 3000:
        _fail("full-wall wardrobe should span the wall (got %dmm)" % wardrobe["width_mm"])
    # window clearance rule must be present for rooms with windows
    if not any(c.get("action") == "keep_window_clear" for c in rooms["主卧"]["opening_constraints"]):
        _fail("master bedroom should record a window clearance constraint")

    # 布局方案.json mirrors the draft
    with open(result["layout_json"], "r", encoding="utf-8") as f:
        layout_json = json.load(f)
    if layout_json.get("status") != "draft":
        _fail("布局方案.json should mirror the M4 draft")
    return {
        "rooms": sorted(rooms.keys()),
        "wardrobe_width_mm": wardrobe["width_mm"],
        "assumptions": len(draft.get("assumptions") or []),
        "pptx_size": os.path.getsize(result["pptx"]),
        "layout_draft_json": result["layout_draft_json"],
    }


def scenario_cad(tmp):
    from core.cad_reader import read_dxf_with_rooms
    from core.space_profile import build_space_cognition_package
    from core.needs_profile import build_needs_cognition_package
    from core.automation_gate import build_automation_gate_package
    from core.layout_draft import build_layout_draft

    case_dir = os.path.join(tmp, "cad_case")
    os.makedirs(case_dir, exist_ok=True)
    conditions_path = os.path.join(case_dir, "design_conditions.json")
    dxf_path = os.path.join(case_dir, "bedroom.dxf")
    _cad_bedroom_conditions(conditions_path)
    _bedroom_dxf(dxf_path)

    with open(conditions_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    cad_plan = read_dxf_with_rooms(dxf_path)
    space_package = build_space_cognition_package(
        conditions, case_dir, cad_plan=cad_plan, source_files={"cad": dxf_path})
    needs_package = build_needs_cognition_package(
        conditions, case_dir, space_profile=space_package["profile"])
    gate_package = build_automation_gate_package(
        space_package["profile"], needs_package["profile"], case_dir)
    gate = gate_package["gate"]
    if "layout_draft" not in gate["allowed"]:
        _fail("gate should allow layout_draft for CAD bedroom case")

    draft = build_layout_draft(space_package["profile"], needs_package["profile"], gate=gate)
    rooms = _check_draft_common(draft, ["主卧"])
    room = rooms["主卧"]

    door_constraints = [c for c in room["opening_constraints"] if c.get("action") == "avoid_door_swing"]
    if not door_constraints:
        _fail("CAD bedroom should record a door-swing avoidance constraint")
    door_walls = {c.get("wall") for c in door_constraints}
    wardrobe = next((f for f in room["furniture"] if "衣柜" in f.get("item", "")), None)
    if wardrobe is None:
        _fail("CAD bedroom should include a wardrobe")
    if wardrobe.get("against_wall") in door_walls:
        _fail("wardrobe must not sit on the door wall (%s)" % wardrobe.get("against_wall"))
    return {
        "door_walls": sorted(door_walls),
        "wardrobe_wall": wardrobe.get("against_wall"),
        "wardrobe_size": [wardrobe["width_mm"], wardrobe["depth_mm"]],
    }


def scenario_blocked(tmp):
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package
    from core.layout_draft import build_layout_draft
    from core.space_profile import build_space_cognition_package
    from core.needs_profile import build_needs_cognition_package
    from core.automation_gate import build_automation_gate_package

    case_dir = os.path.join(tmp, "blocked_case")
    os.makedirs(case_dir, exist_ok=True)
    conditions_path = os.path.join(case_dir, "design_conditions.json")
    shutil.copy2(os.path.join(ROOT, "templates", "design_conditions.sample.json"), conditions_path)

    with open(conditions_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    space_package = build_space_cognition_package(conditions, case_dir)
    needs_package = build_needs_cognition_package(
        conditions, case_dir, space_profile=space_package["profile"])
    gate_package = build_automation_gate_package(
        space_package["profile"], needs_package["profile"], case_dir)
    gate = gate_package["gate"]
    if "layout_draft" in gate["allowed"]:
        _fail("gate must block layout_draft without geometry facts")

    draft = build_layout_draft(space_package["profile"], needs_package["profile"], gate=gate)
    if draft.get("status") != "blocked_by_automation_gate":
        _fail("build_layout_draft should return blocked status, got %s" % draft.get("status"))
    if draft.get("rooms"):
        _fail("blocked draft must not fabricate rooms")

    result = run_mvp_concept_package(conditions_path)
    if "layout_draft" in result.get("allowed_modules", []):
        _fail("pipeline should keep layout_draft blocked for sample conditions")
    if result.get("layout_draft_json"):
        _fail("pipeline must not write layout_draft.json when blocked")
    with open(result["layout_json"], "r", encoding="utf-8") as f:
        layout_json = json.load(f)
    if layout_json.get("status") != "blocked_by_automation_gate":
        _fail("布局方案.json should keep blocked status")
    if not layout_json.get("reasons"):
        _fail("blocked layout should carry reasons")
    if not os.path.exists(result["pptx"]):
        _fail("blocked scenario should still produce the concept PPTX")
    return {"blocked_reasons": len(layout_json["reasons"])}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        scan_result = scenario_scan(tmp)
        cad_result = scenario_cad(tmp)
        blocked_result = scenario_blocked(tmp)

    print(json.dumps({
        "ok": True,
        "scan_scenario": scan_result,
        "cad_scenario": cad_result,
        "blocked_scenario": blocked_result,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
