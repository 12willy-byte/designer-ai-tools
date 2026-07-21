#!/usr/bin/env python3
"""门洞统一访问层（get_doors 四级口径 + 预算/布局口径归一）离线验收。

背景：假洞物理分层（方案 b）——door_details 扁平结构不变、假洞永留痕，
语义口径单点定义在 core.door_access。本脚本锁定：
1. 双图四级口径数值（details 级语义全集）：
   露露姨 usable=3 / countable=6 / openings=19 / all=26；
   罗菁融合 usable=6 / countable=12 / openings=13 / all=13；
2. 留痕回归：all 级保留全部降级洞的 wide_arc_downgrade evidence；
3. 口径归一（核心）：同一图纸，预算室内门樘数 == 布局摘要门数
   （露露姨=5、罗菁=8——附着墙面后的子集，两模块同源故必然相等）；
4. 无语义分级输入（扫描/手动/DXF，door_type 为空）维持原口径全部计入。

运行：AI_DEMO_MODE=1 python3 scripts/validate_door_access.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLE_DIR = os.path.join(ROOT, "resources", "real_samples")
LULUYI_PDF = os.path.join(SAMPLE_DIR, "露露姨出租房平面.pdf")
STRUCTURE_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳原始图.pdf")
FURNISHED_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳平面.pdf")


def _fail(message):
    raise SystemExit("validate_door_access FAILED: " + message)


def _check_levels(label, details, expected):
    from core.door_access import get_doors
    got = {lv: len(get_doors(details, lv)) for lv in ("usable", "countable", "openings", "all")}
    if got != expected:
        _fail("%s 四级口径漂移：期望 %s，got %s" % (label, expected, got))
    try:
        get_doors(details, "bogus")
        _fail("未知 level 必须报错")
    except ValueError:
        pass
    return got


def _check_consistency(label, cad_plan, expected_count):
    """预算室内门樘数 == 布局摘要门数（口径归一核心断言）。"""
    from core.automation_gate import build_automation_gate
    from core.budget_estimate import build_budget_estimate
    from core.layout_draft import build_layout_draft
    from core.needs_profile import build_needs_profile
    from core.space_profile import build_space_profile

    conditions = {
        "project": {"name": label + "口径归一样例", "house_type": "两居室", "area_m2": 60},
        "family": {"residents": "2人"},
        "style": {"primary_style": "现代简约"},
        "budget": {"total_budget": 100000},
        "special_requirements": {"承重墙": "不可拆改", "上下水": "湿区不可移动"},
    }
    space = build_space_profile(conditions, cad_plan=cad_plan)
    needs = build_needs_profile(conditions, space_profile=space)
    gate = build_automation_gate(space, needs)
    if "layout_draft" not in gate["allowed"]:
        _fail("%s 布局草案应被闸门放行（含降级），got %s" % (label, gate.get("blocked")))
    draft = build_layout_draft(space, needs, gate=gate)
    layout_doors = (draft.get("source_facts") or {}).get("door_count")
    estimate = build_budget_estimate(space, needs, layout_draft=draft)
    door_item = next((it for it in estimate.get("whole_house_items") or []
                      if it.get("item") == "室内门（含门套）"), None)
    budget_doors = door_item.get("quantity") if door_item else None
    if layout_doors != budget_doors:
        _fail("%s 口径未归一：布局摘要门数 %s != 预算门樘数 %s"
              % (label, layout_doors, budget_doors))
    if layout_doors != expected_count:
        _fail("%s 归一门数应为 %d，got %d" % (label, expected_count, layout_doors))
    return {"layout_doors": layout_doors, "budget_doors": budget_doors}


def main():
    from core.pdf_plan_reader import read_pdf_plan
    from core.plan_fusion import fuse_plans

    for path in (LULUYI_PDF, STRUCTURE_PDF, FURNISHED_PDF):
        if not os.path.exists(path):
            _fail("真实样本缺失：%s" % path)

    luluyi = read_pdf_plan(LULUYI_PDF)
    fused = fuse_plans(read_pdf_plan(STRUCTURE_PDF), read_pdf_plan(FURNISHED_PDF))

    luluyi_levels = _check_levels(
        "露露姨", luluyi.get("door_details"),
        {"usable": 3, "countable": 6, "openings": 19, "all": 26})
    luojing_levels = _check_levels(
        "罗菁融合", fused.get("door_details"),
        {"usable": 6, "countable": 12, "openings": 13, "all": 13})

    # 留痕回归：all 级完整保留降级洞的判定依据（假洞永不物理删除）
    downgraded = [d for d in (luluyi.get("door_details") or [])
                  if "wide_arc_downgrade" in (d.get("evidence") or [])]
    if len(downgraded) < 8:
        _fail("露露姨 all 级应保留 ≥8 条 wide_arc_downgrade 留痕，got %d"
              % len(downgraded))

    # 无语义分级输入：door_type 为空维持原口径全部计入
    from core.door_access import counts_as_interior_door, get_doors
    if not counts_as_interior_door({"kind": "door", "door_type": None, "width_mm": 800}):
        _fail("door_type 为空的旧输入必须维持原口径计入")
    legacy = [{"type": None, "width_mm": 800}, {"type": None, "width_mm": 3000}]
    if len(get_doors(legacy, "countable")) != 2:
        _fail("旧输入 countable 必须全部计入")

    result = {
        "ok": True,
        "luluyi_levels": luluyi_levels,
        "luojing_levels": luojing_levels,
        "luluyi_consistency": _check_consistency("露露姨", luluyi, 5),
        "luojing_consistency": _check_consistency("罗菁融合", fused, 8),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
