#!/usr/bin/env python3
"""含家具布置图泛化改进（四项普适改进）离线验收。

背景：第二套真实图纸（露露姨出租房单张含家具布置图）暴露四个结构性差距：
1. 家具线条过滤：未配对浮动单线（家具/标注轮廓）形成假闭环——净宽 <1m
   的条带必须剔除并留痕，且最终房间清单不得有净宽 <1m 的"房间"；
2. 命名环内优先：环内名字绝对优先，环外兜底命名必须未被其他闭环占用，
   且标 name_source=nearest_outside + 低置信；
3. 门宽物理先验：宽度 >1.2m 的洞口即使有弧线佐证也不得判为 door
   （推拉门/阳台口/并门误判），降级 opening 并留痕 wide_arc_downgrade；
4. 无窗降级模式：门洞/结构/机电齐全但缺采光面时，闸门放行布局草案并
   标记 draft_degraded；缺门洞几何仍拦截。

同时锁定罗菁深圳回归基线（比例/房间/门/窗不得回退）与预算门分项口径
（超宽/未证实洞口不计入室内门工程量）。

运行：AI_DEMO_MODE=1 python3 scripts/validate_furnished_generalization.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLE_DIR = os.path.join(ROOT, "resources", "real_samples")
LULUYI_PDF = os.path.join(SAMPLE_DIR, "露露姨出租房平面.pdf")
STRUCTURE_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳原始图.pdf")
FURNISHED_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳平面.pdf")


def _fail(message):
    raise SystemExit("validate_furnished_generalization FAILED: " + message)


def _room_dims(room):
    pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
    if len(pts) < 3:
        return 0, 0
    w = max(p[0] for p in pts) - min(p[0] for p in pts)
    h = max(p[1] for p in pts) - min(p[1] for p in pts)
    return w, h


def _check_luluyi(plan):
    """露露姨单布置图：四项改进的前三项 + 比例零漂移。"""
    if not plan.get("accepted"):
        _fail("露露姨样本未被接受")
    meta = plan["pdf"]
    if abs(meta["pt_to_mm"] - 6.4458) / 6.4458 > 0.01:
        _fail("露露姨比例校准漂移：%s" % meta["pt_to_mm"])

    # 1) 家具线条过滤（净宽 <1m 断言含方案三豁免：文字锚定的合法条带除外）
    rooms = plan["detected_rooms"]
    for room in rooms:
        w, h = _room_dims(room)
        if w and h and min(w, h) < 1000.0 and not room.get("strip_space"):
            _fail("房间清单仍含净宽 <1m 的假房间：%s（%.0fx%.0f）"
                  % (room.get("name"), w, h))
    # 方案三 a：文字锚定豁免——两个阳台条带复活且留痕完整
    strips = [r for r in rooms if r.get("strip_space")]
    if len(strips) != 2 or any(r.get("space_kind") != "阳台" for r in strips):
        _fail("露露姨应有 2 个文字锚定豁免的阳台条带，got %s"
              % [(r.get("name"), r.get("space_kind")) for r in strips])
    if any(not r.get("net_width_mm") for r in strips):
        _fail("豁免条带必须留痕净宽（net_width_mm）")
    # 防误伤锁：1.05m 次卧条带无文字锚，不得豁免升级
    strip_room = next((r for r in rooms if r.get("name") == "次卧"), None)
    if strip_room and strip_room.get("strip_space"):
        _fail("次卧条带不得获得 strip_space 豁免（无环内文字锚）")
    removed = plan.get("removed_rooms") or []
    if len(removed) < 1:
        _fail("露露姨应至少剔除 1 个假闭环（细条/微小环），got %d" % len(removed))
    if not all(r.get("reasons") for r in removed):
        _fail("剔除的假房间必须带理由留痕")
    if any((r.get("area_m2") or 0) > 1.0 and "细条" not in r["reasons"][0]
           for r in removed):
        _fail("文字锚定的阳台条带不应再被剔除，got %s"
              % [(r["name"], r["area_m2"]) for r in removed])
    if (plan.get("furniture_lines") or {}).get("count", 0) <= 0:
        _fail("含家具布置图应标记出浮动单线（furniture_lines）")
    names = {r.get("name") for r in rooms}
    if "厨房" not in names or "主卧" not in names:
        _fail("厨房/主卧必须保留且名实相符，got %s" % sorted(names))
    usable = {"客厅", "厨房", "主卧", "次卧", "客卫"} & names
    if len(usable) < 3:
        _fail("可用房间（名实相符+低置信兜底）应 ≥3/7，got %s" % sorted(usable))

    # 2) 命名环内优先：环外兜底命名必须低置信留痕
    fallback_named = [r for r in rooms if r.get("name_source") == "nearest_outside"]
    for room in fallback_named:
        if room.get("name_confidence") != "low":
            _fail("环外兜底命名必须标低置信：%s" % room.get("name"))
    lim = "；".join(plan.get("limitations") or [])
    if "兜底命名" not in lim and "未命名空间" not in lim:
        _fail("命名诚实化 limitation 缺失")

    # 3) 门宽物理先验：不得有 >1.2m 的 door
    details = plan.get("door_details") or []
    wide_doors = [d for d in details
                  if d.get("type") == "door" and (d.get("width_mm") or 0) > 1200]
    if wide_doors:
        _fail("仍有超宽假门判为 door：%s"
              % [(d["id"], d["width_mm"]) for d in wide_doors])
    downgraded = [d for d in details if "wide_arc_downgrade" in (d.get("evidence") or [])]
    if len(downgraded) < 4:
        _fail("露露姨应有 ≥4 个超宽洞口被物理先验降级，got %d" % len(downgraded))
    if any(d.get("type") != "opening" for d in downgraded):
        _fail("超宽降级洞口必须判为 opening")

    # 5) 复合环命名（方案 b+d）：22.82㎡ 大环不得静默无名——
    #    要么亲和度命名（affinity_outside + 低置信 + 评分留痕），
    #    要么 naming_hint + questions_to_confirm 生成"疑似客厅"待确认问题。
    big = next((r for r in rooms if (r.get("area_m2") or 0) >= 20), None)
    if not big:
        _fail("露露姨应有 ≥20㎡ 的客厅大闭环")
    if big.get("name_source") == "affinity_outside":
        if big.get("name_confidence") != "low" or not big.get("name_affinity"):
            _fail("亲和度命名必须标低置信并带评分留痕：%s" % big.get("name"))
        big_naming = "affinity:" + big["name"]
    else:
        hint = big.get("naming_hint") or {}
        if hint.get("nearest_free_text") != "客厅":
            _fail("22.82㎡ 环未获命名时命名线索应为“客厅”，got %s" % hint)
        from core.space_profile import build_space_profile
        profile = build_space_profile({}, cad_plan=plan)
        naming_qs = [q for q in profile.get("questions_to_confirm") or []
                     if q.get("category") == "room_naming"]
        if not any("客厅" in (q.get("question") or "") for q in naming_qs):
            _fail("22.82㎡ 大环静默无名：缺少“疑似客厅”待确认问题，got %s"
                  % [q.get("question") for q in naming_qs])
        big_naming = "question:" + naming_qs[0]["question"][:30]
        # 方案三 d：走廊有文字未成环 → 必须提问兜底（本期不造虚拟环）
        strip_qs = [q for q in profile.get("questions_to_confirm") or []
                    if q.get("category") == "strip_space"]
        if not any("走廊" in (q.get("question") or "") for q in strip_qs):
            _fail("走廊文字未成环时必须生成待确认问题，got %s"
                  % [q.get("question") for q in strip_qs])
        if any("阳台" in (q.get("question") or "") for q in strip_qs):
            _fail("阳台文字已用作命名来源，不应再报未成环提问")
        # 方案四 b+d：主卧 L 形残环必须标注 partial + 降置信 + 面积缩水提问
        master = next((r for r in rooms if r.get("name") == "主卧"), None)
        if not master or not master.get("partial"):
            _fail("露露姨主卧 7.57㎡（22 边/满框 0.51）必须标 partial=true")
        if not master.get("partial_reasons") or not master.get("partial_bbox_area_m2"):
            _fail("partial 环必须带 partial_reasons 与 partial_bbox_area_m2 留痕")
        partial_qs = [q for q in profile.get("questions_to_confirm") or []
                      if q.get("category") == "partial_room"]
        if not any("主卧" in (q.get("question") or "") for q in partial_qs):
            _fail("主卧残环必须生成面积缩水待确认问题，got %s"
                  % [q.get("question") for q in partial_qs])
        # 防误伤：满框率正常的环、strip_space 条带不得标 partial
        for r in rooms:
            if r.get("name") != "主卧" and r.get("partial"):
                _fail("露露姨仅主卧应标 partial，%s（%.2f㎡）被误标"
                      % (r.get("name"), r.get("area_m2") or 0))
    # 次卧条带不得经亲和度路径获新名（保持旧路径低置信兜底）
    strip_room = next((r for r in rooms if r.get("name") == "次卧"), None)
    if strip_room and strip_room.get("name_source") != "nearest_outside":
        _fail("次卧条带不得经亲和度路径改名：%s" % strip_room.get("name_source"))
    return {
        "pt_to_mm": meta["pt_to_mm"],
        "rooms": {r.get("name"): r.get("area_m2") for r in rooms},
        "removed_rooms": len(removed),
        "furniture_lines": plan["furniture_lines"]["count"],
        "door_details": len(details),
        "door_typed": sum(1 for d in details if d.get("type") == "door"),
        "wide_downgraded": len(downgraded),
        "fallback_named": [r.get("name") for r in fallback_named],
        "big_room_naming": big_naming,
    }


def _check_luojing_regression(structure, furnished, fused):
    """罗菁基线回归：比例/房间/门/窗逐项不得回退。"""
    if abs(structure["pdf"]["pt_to_mm"] - 7.20777) / 7.20777 > 0.002:
        _fail("罗菁原始图比例漂移：%s" % structure["pdf"]["pt_to_mm"])
    if len(structure["detected_rooms"]) != 9:
        _fail("罗菁原始图房间数应为 9，got %d" % len(structure["detected_rooms"]))
    rooms = fused.get("detected_rooms") or []
    if len(rooms) != 10:
        _fail("罗菁融合房间数应为 10（含主卧 plan_only），got %d" % len(rooms))
    master = next((r for r in rooms if r.get("name") == "主卧"), None)
    if not master or master.get("source") != "plan_only":
        _fail("主卧必须保持 plan_only 并入")
    stats = (fused.get("fusion") or {}).get("door_fusion", {}).get("stats", {})
    if stats.get("converged_total") != 13:
        _fail("罗菁门收敛应为 13，got %s" % stats.get("converged_total"))
    if (stats.get("door_dual", 0) + stats.get("door_single", 0)
            + stats.get("door_plan_only", 0)) != 6:
        _fail("罗菁 door 应为 6，got %s" % stats)
    if stats.get("opening") != 7:
        _fail("罗菁 opening 应为 7，got %s" % stats.get("opening"))
    if fused.get("window_count") != 10:
        _fail("罗菁窗应为 10，got %s" % fused.get("window_count"))
    # 门宽物理先验对罗菁同样生效：融合后不得有 >1.2m 的 door
    for det in fused.get("door_details") or []:
        if det.get("type") == "door" and (det.get("width_mm") or 0) > 1200:
            _fail("罗菁融合出现 >1.2m 的 door：%s" % det.get("width_mm"))
    # 复合环命名对罗菁零漂移：双图均不得出现亲和度改名；
    # 6.08㎡ 环必须保持"未命名空间3"（防漂移锁定）
    for label, parsed in (("原始图", structure), ("平面图", furnished)):
        for room in parsed.get("detected_rooms") or []:
            if room.get("name_source") == "affinity_outside":
                _fail("罗菁%s 出现亲和度改名（基线漂移）：%s（%.2f㎡）"
                      % (label, room.get("name"), room.get("area_m2") or 0))
    struct_names = {r.get("name") for r in structure["detected_rooms"]}
    if "未命名空间3" not in struct_names:
        _fail("罗菁原始图 6.08㎡ 环必须保持 未命名空间3，got %s"
              % sorted(struct_names))
    # 方案三 c：位置/形态类型推断——两"阳台带"标 inferred_type 但不改名
    inferred = {r.get("name"): r.get("inferred_type")
                for r in structure["detected_rooms"] if r.get("inferred_type")}
    if inferred != {"未命名空间": "阳台", "未命名空间2": "阳台"}:
        _fail("罗菁原始图类型推断应为 未命名空间/未命名空间2=阳台，got %s" % inferred)
    ring3 = next(r for r in structure["detected_rooms"]
                 if r.get("name") == "未命名空间3")
    if ring3.get("inferred_type"):
        _fail("6.08㎡ 环（长宽比 2.4）不得被推断类型，got %s"
              % ring3.get("inferred_type"))
    # 方案四：罗菁原始图零 partial（满框率均正常；63.14㎡ 复合环合法形态
    # 必须排除——残环标注对罗菁基线零漂移）
    struct_partials = [r.get("name") for r in structure["detected_rooms"]
                       if r.get("partial")]
    if struct_partials:
        _fail("罗菁原始图不得有 partial 标注（零漂移），got %s" % struct_partials)
    return {
        "structure_scale": structure["pdf"]["pt_to_mm"],
        "structure_rooms": len(structure["detected_rooms"]),
        "fused_rooms": len(rooms),
        "doors": stats.get("converged_total"),
        "windows": fused.get("window_count"),
    }


def _check_degraded_gate():
    """改进 4：缺窗降级放行、缺门洞仍拦截。"""
    from core.automation_gate import build_automation_gate, explain_degraded_module
    from core.needs_profile import build_needs_profile
    from core.space_profile import build_space_profile

    conditions = {
        "project": {"name": "降级样例", "house_type": "两居室", "area_m2": 60},
        "family": {"residents": "2人"},
        "style": {"primary_style": "现代简约", "keywords": "清爽"},
        "budget": {"total_budget": 100000},
        "special_requirements": {"承重墙": "不可拆改", "上下水": "湿区不可移动"},
    }
    cad_plan = {
        "source_type": "pdf_vector", "accepted": True, "confidence": 0.66,
        "walls": [], "doors": [(0, 0, 900, 0)], "windows": [],
        "door_details": [{
            "id": "gap_0", "type": "door", "start": [0, 0], "end": [900, 0],
            "width_mm": 900.0, "exterior": False, "connects": ["主卧"],
            "evidence": ["wall_gap", "door_arc"], "confidence": 0.75,
            "source": "structure",
        }],
        "detected_rooms": [
            {"name": "主卧", "area_m2": 12.0,
             "floor_points": [{"x": 0, "y": 0}, {"x": 4000, "y": 0},
                              {"x": 4000, "y": 3000}, {"x": 0, "y": 3000}]},
        ],
        "bounds": (0, 0, 4000, 3000), "limitations": [],
    }
    space = build_space_profile(conditions, cad_plan=cad_plan)
    needs = build_needs_profile(conditions, space_profile=space)
    gate = build_automation_gate(space, needs)
    if "layout_draft" not in gate["allowed"]:
        _fail("缺窗但门洞/结构/机电齐全时，布局草案应降级放行而非拦截")
    degraded = explain_degraded_module(gate, "layout_draft")
    if not degraded or degraded.get("mode") != "draft_degraded":
        _fail("闸门应标记 layout_draft 为 draft_degraded 降级模式")

    from core.layout_draft import build_layout_draft
    draft = build_layout_draft(space, needs, gate=gate)
    if draft.get("status") != "draft":
        _fail("降级模式下应生成布局草案，got %s" % draft.get("status"))
    if draft.get("layout_mode") != "draft_degraded":
        _fail("草案应标记 layout_mode=draft_degraded")
    text = json.dumps(draft.get("assumptions") or [], ensure_ascii=False)
    if "采光面未知" not in text:
        _fail("降级草案必须标注'采光面未知'假设")

    # 缺门洞几何：仍拦截
    cad_no_doors = dict(cad_plan, doors=[], door_details=[])
    space2 = build_space_profile(conditions, cad_plan=cad_no_doors)
    needs2 = build_needs_profile(conditions, space_profile=space2)
    gate2 = build_automation_gate(space2, needs2)
    if "layout_draft" in gate2["allowed"]:
        _fail("缺门洞几何时布局草案必须仍被拦截")
    return {"degraded_allowed": True, "no_doors_blocked": True}


def _check_budget_door_rule():
    """预算门分项口径：超宽/未证实洞口不计入室内门工程量。"""
    from core.budget_estimate import _counts_as_interior_door
    cases = [
        ({"kind": "door", "door_type": "door", "width_mm": 800}, True),
        ({"kind": "door", "door_type": "opening", "width_mm": 900}, True),
        ({"kind": "door", "door_type": "opening", "width_mm": 3000}, False),
        ({"kind": "door", "door_type": "unverified", "width_mm": 800}, False),
        ({"kind": "door", "door_type": None, "width_mm": 800}, True),
        ({"kind": "window", "door_type": None, "width_mm": 1500}, False),
    ]
    for op, expected in cases:
        if _counts_as_interior_door(op) != expected:
            _fail("门工程量口径错误：%s 应为 %s" % (op, expected))
    return {"budget_door_rule": True}


def main():
    from core.pdf_plan_reader import read_pdf_plan
    from core.plan_fusion import fuse_plans

    if not (os.path.exists(LULUYI_PDF) and os.path.exists(STRUCTURE_PDF)
            and os.path.exists(FURNISHED_PDF)):
        _fail("真实样本缺失：resources/real_samples/")

    luluyi = read_pdf_plan(LULUYI_PDF)
    structure = read_pdf_plan(STRUCTURE_PDF)
    furnished = read_pdf_plan(FURNISHED_PDF)
    fused = fuse_plans(structure, furnished)

    result = {
        "ok": True,
        "luluyi": _check_luluyi(luluyi),
        "luojing_regression": _check_luojing_regression(structure, furnished, fused),
        "degraded_gate": _check_degraded_gate(),
        "budget": _check_budget_door_rule(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
