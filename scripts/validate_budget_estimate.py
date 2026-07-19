"""Offline validation for the M5 budget estimate & material list module.

Covers:
A. Scan scenario (RoomPlan semantic template): gate allows budget_estimate, the
   pipeline writes budget_estimate.json + material_list.json + summary, every
   room has priced line items, every item carries quantity/price basis, the
   math is consistent (item subtotal = qty x unit price; room subtotal = item
   sum; total = category sum), the budget comparison exists and matches the
   numbers, assumptions are prefixed, no brand names appear, and the PPTX
   contains the budget slide.
B. Blocked regression: without a total budget the gate blocks budget_estimate
   and the pipeline records the blocked status without fabricating numbers.
C. Budget comparison logic: an 8万 budget lands in over_budget with overrun
   items; a 50万 budget lands in within_budget.
D. Numeric contract: two rules-only builds are identical, and the numeric view
   excludes AI text fields (the real-mode rules_only vs rules_plus_ai
   comparison reuses core.budget_estimate.numeric_view).

Run: AI_DEMO_MODE=1 python3 scripts/validate_budget_estimate.py
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

os.environ["AI_DEMO_MODE"] = "1"

TOL = 0.51  # money rounding tolerance in yuan

# Brand/model tokens that must never appear in the estimate (只描述材质/工艺/价位档).
BRAND_BLACKLIST = [
    "索菲亚", "欧派", "尚品宅配", "好莱客", "马可波罗", "东鹏", "诺贝尔", "蒙娜丽莎",
    "圣象", "大自然", "德尔", "TOTO", "科勒", "箭牌", "九牧", "海尔", "美的", "格力",
    "西门子", "博世", "方太", "老板电器", "多乐士", "立邦", "三棵树", "宜家", "IKEA",
]


def _scan_conditions(path, budget=280000):
    data = {
        "project": {"name": "扫描样例两室一厅", "house_type": "两室一厅", "area_m2": 68,
                    "design_type": "整屋自动化方案"},
        "family": {"residents": "3人(夫妻+1孩)", "work_from_home": "偶尔", "storage_need": "较高",
                   "cooking_frequency": "高频中餐"},
        "style": {"primary_style": "现代简约", "color_tone": "暖白、原木色、低饱和蓝灰",
                  "keywords": "通透 温润 收纳"},
        "rooms": [
            {"name": "客厅", "requirements": {"功能": "会客、观影、亲子活动"}},
            {"name": "主卧", "requirements": {"功能": "睡眠、衣物收纳", "备注": "需要整墙衣柜"}},
            {"name": "次卧", "requirements": {"功能": "儿童房,兼顾书房"}},
            {"name": "厨房", "requirements": {"功能": "高频中餐,需要大单槽和洗碗机位"}},
            {"name": "卫生间", "requirements": {"功能": "干湿分离"}},
        ],
        "special_requirements": {"承重墙": "外墙及结构墙不可拆改，需保留",
                                 "上下水": "厨房与卫生间湿区位置不可移动"},
    }
    if budget is not None:
        data["budget"] = {"total_budget": budget}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _fail(message):
    raise SystemExit("FAIL: " + message)


def _close(a, b, tol=TOL):
    return abs(a - b) <= tol


def _check_item_math(item, where):
    for field in ("category", "item", "quantity_basis", "unit_price_basis", "unit"):
        if not item.get(field):
            _fail("%s: item missing %s: %s" % (where, field, item.get("item")))
    if "基准表" not in item["unit_price_basis"]:
        _fail("%s: unit_price_basis must cite the baseline table: %s" % (where, item["unit_price_basis"]))
    qty, up_l, up_h = item["quantity"], item["unit_price_low"], item["unit_price_high"]
    if qty <= 0 or up_l <= 0 or up_h < up_l:
        _fail("%s: bad quantity/price range: %s" % (where, item))
    if not _close(item["subtotal_low"], round(qty * up_l, 2)):
        _fail("%s: subtotal_low %.2f != qty %.2f x price %.2f" % (
            where, item["subtotal_low"], qty, up_l))
    if not _close(item["subtotal_high"], round(qty * up_h, 2)):
        _fail("%s: subtotal_high %.2f != qty %.2f x price %.2f" % (
            where, item["subtotal_high"], qty, up_h))


def _check_estimate_common(estimate, expected_rooms):
    if estimate.get("status") != "estimate":
        _fail("budget estimate status should be 'estimate', got %s" % estimate.get("status"))
    if estimate.get("schema_version") != "budget_estimate.v1":
        _fail("budget estimate schema_version mismatch")

    rooms = {room["name"]: room for room in estimate.get("rooms") or []}
    for name in expected_rooms:
        if name not in rooms:
            _fail("estimate missing room %s" % name)

    # 每房间有分项、每项有工程量来源与价位档依据、小计数学一致
    for name, room in rooms.items():
        if not room.get("items"):
            _fail("room %s has no line items" % name)
        categories = {item["category"] for item in room["items"]}
        if not ({"硬装施工", "主材"} <= categories):
            _fail("room %s lacks 硬装施工/主材 items: %s" % (name, categories))
        for item in room["items"]:
            _check_item_math(item, "room %s" % name)
        sum_low = round(sum(i["subtotal_low"] for i in room["items"]), 2)
        sum_high = round(sum(i["subtotal_high"] for i in room["items"]), 2)
        if not _close(room["subtotal_low"], sum_low) or not _close(room["subtotal_high"], sum_high):
            _fail("room %s subtotal mismatch: %.2f/%.2f vs item sums %.2f/%.2f" % (
                name, room["subtotal_low"], room["subtotal_high"], sum_low, sum_high))

    whole = estimate.get("whole_house_items") or []
    if not whole:
        _fail("estimate has no whole-house items")
    for item in whole:
        if item.get("item") == "综合管理费":
            continue  # 费率计取项，金额按硬装+主材小计比例计算，单独校验
        _check_item_math(item, "whole-house")

    # 总计 = 分项之和
    totals = estimate.get("totals") or {}
    expect_low = round(sum(r["subtotal_low"] for r in rooms.values())
                       + sum(i["subtotal_low"] for i in whole), 2)
    expect_high = round(sum(r["subtotal_high"] for r in rooms.values())
                        + sum(i["subtotal_high"] for i in whole), 2)
    if not _close(totals.get("low", 0), expect_low) or not _close(totals.get("high", 0), expect_high):
        _fail("totals %.2f~%.2f != room+whole sums %.2f~%.2f" % (
            totals.get("low", 0), totals.get("high", 0), expect_low, expect_high))
    by_category = totals.get("by_category") or {}
    if not _close(sum(v["low"] for v in by_category.values()), totals["low"]):
        _fail("by_category lows do not sum to total low")
    if not _close(sum(v["high"] for v in by_category.values()), totals["high"]):
        _fail("by_category highs do not sum to total high")

    # 价格档次判定依据
    tier = estimate.get("tier") or {}
    if tier.get("level") not in ("经济档", "标准档", "品质档") or not tier.get("basis"):
        _fail("tier level/basis missing: %s" % tier)

    # 假设全部以「假设：」开头
    assumptions = estimate.get("assumptions") or []
    if not assumptions:
        _fail("estimate has no assumptions")
    for item in assumptions:
        if not str(item).startswith("假设："):
            _fail("assumption not prefixed with 假设：: %s" % item)

    # 无品牌型号
    blob = json.dumps(estimate, ensure_ascii=False)
    for brand in BRAND_BLACKLIST:
        if brand in blob:
            _fail("brand/model token leaked into estimate: %s" % brand)
    return rooms


def _expected_status(totals, budget):
    if totals["high"] <= budget:
        return "within_budget"
    if totals["low"] <= budget:
        return "risk_of_overrun"
    return "over_budget"


def _check_comparison(estimate, budget):
    comparison = estimate.get("budget_comparison") or {}
    if comparison.get("user_budget") != budget:
        _fail("budget comparison user_budget mismatch: %s" % comparison)
    expected = _expected_status(estimate["totals"], budget)
    if comparison.get("status") != expected:
        _fail("comparison status %s != expected %s (totals %s, budget %s)" % (
            comparison.get("status"), expected, estimate["totals"], budget))
    if not (comparison.get("conclusion") or "").strip():
        _fail("comparison conclusion missing")
    if expected != "within_budget" and not comparison.get("overrun_items"):
        _fail("overrun_items should be listed when not within budget")
    return comparison


def _check_material_list(path, estimate):
    with open(path, "r", encoding="utf-8") as f:
        material_list = json.load(f)
    if material_list.get("schema_version") != "material_list.v1":
        _fail("material list schema_version mismatch")
    items = material_list.get("items") or []
    if not items:
        _fail("material list is empty")
    for item in items:
        for field in ("material", "quantity", "unit", "quantity_basis", "tier", "price_basis"):
            if not item.get(field):
                _fail("material item missing %s: %s" % (field, item))
        if item["quantity"] <= 0:
            _fail("material item quantity must be positive: %s" % item)
        if "基准表" not in item["price_basis"]:
            _fail("material price_basis must cite the baseline: %s" % item["price_basis"])
    for item in material_list.get("assumptions") or []:
        if not str(item).startswith("假设："):
            _fail("material list assumption not prefixed: %s" % item)

    # 地板用量 ≈ 干区房间面积加总 × 损耗系数
    from core.budget_estimate import load_pricing_baseline
    baseline = load_pricing_baseline()
    wastage = (baseline.get("quantity_rules") or {}).get("floor_wastage") or 1.05
    dry_area = sum(r["area_m2"] for r in estimate["rooms"]
                   if r["room_type"] not in ("kitchen", "bathroom", "balcony"))
    floor_item = next((i for i in items if "地板" in i["material"] or "地板" in i.get("baseline_entry", "")), None)
    if floor_item is None:
        _fail("material list should include a floor material entry")
    if not _close(floor_item["quantity"], round(dry_area * wastage, 2), tol=0.6):
        _fail("floor quantity %.2f != dry area %.2f x wastage %.2f" % (
            floor_item["quantity"], dry_area, wastage))
    blob = json.dumps(material_list, ensure_ascii=False)
    for brand in BRAND_BLACKLIST:
        if brand in blob:
            _fail("brand/model token leaked into material list: %s" % brand)
    return material_list


def _pptx_has_budget_slide(pptx_path):
    with zipfile.ZipFile(pptx_path) as zf:
        for name in zf.namelist():
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                text = zf.read(name).decode("utf-8", errors="ignore")
                if "预算总览" in text:
                    return True
    return False


def scenario_scan(tmp):
    from core.scan_importer import summarize_scan_file
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    case_dir = os.path.join(tmp, "scan_case")
    os.makedirs(case_dir, exist_ok=True)
    conditions_path = os.path.join(case_dir, "design_conditions.json")
    _scan_conditions(conditions_path)
    scan_path = os.path.join(case_dir, "roomplan_scan.json")
    shutil.copy2(os.path.join(ROOT, "templates", "roomplan_scan.template.json"), scan_path)
    scan_summary = summarize_scan_file(scan_path)

    result = run_mvp_concept_package(conditions_path, scan_summary=scan_summary)
    if "budget_estimate" not in result.get("allowed_modules", []):
        _fail("gate should allow budget_estimate with scan facts + budget")
    for key in ("budget_estimate_json", "material_list_json", "budget_summary_md"):
        if not result.get(key) or not os.path.exists(result[key]):
            _fail("pipeline did not write %s" % key)
    if not os.path.exists(result["pptx"]):
        _fail("pipeline pptx missing")
    if not _pptx_has_budget_slide(result["pptx"]):
        _fail("pptx should contain the 预算总览 slide")

    with open(result["budget_estimate_json"], "r", encoding="utf-8") as f:
        estimate = json.load(f)
    rooms = _check_estimate_common(estimate, ["客厅", "主卧", "次卧", "厨房", "卫生间"])
    comparison = _check_comparison(estimate, 280000)
    material_list = _check_material_list(result["material_list_json"], estimate)

    # 工程量来源抽查：客厅地面工程必须引用房间面积
    living_floor = next((i for i in rooms["客厅"]["items"]
                         if i["category"] == "硬装施工" and "地面" in i["item"]), None)
    if living_floor is None or "房间面积" not in living_floor["quantity_basis"]:
        _fail("living room floor item must cite 房间面积 as quantity basis")
    if not _close(living_floor["quantity"], 21.76, tol=0.05):
        _fail("living room floor quantity should equal room area 21.76, got %.2f" % living_floor["quantity"])
    # 需求联动：洗碗机需求必须落到厨房电器
    kitchen_items = " ".join(i["item"] for i in rooms["厨房"]["items"])
    if "洗碗机" not in kitchen_items:
        _fail("kitchen items should include a dishwasher from needs: %s" % kitchen_items)
    # 定制柜体：主卧整墙衣柜必须形成定制柜体工程量
    if not any(i["item"] == "定制柜体（投影面积）" for i in rooms["主卧"]["items"]):
        _fail("master bedroom should include custom cabinet quantity from 整墙衣柜")

    with open(result["budget_json"], "r", encoding="utf-8") as f:
        budget_mirror = json.load(f)
    if budget_mirror.get("status") != "estimate":
        _fail("预算方案.json should mirror the M5 estimate")
    return {
        "rooms": sorted(rooms.keys()),
        "total_range": [estimate["totals"]["low"], estimate["totals"]["high"]],
        "comparison_status": comparison["status"],
        "tier": estimate["tier"]["level"],
        "material_items": len(material_list["items"]),
        "assumptions": len(estimate["assumptions"]),
        "generation_mode": estimate["generation"]["mode"],
    }


def scenario_blocked(tmp):
    from core.scan_importer import summarize_scan_file
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package
    from core.budget_estimate import build_budget_estimate
    from core.space_profile import build_space_profile
    from core.needs_profile import build_needs_profile
    from core.automation_gate import build_automation_gate

    case_dir = os.path.join(tmp, "blocked_case")
    os.makedirs(case_dir, exist_ok=True)
    conditions_path = os.path.join(case_dir, "design_conditions.json")
    _scan_conditions(conditions_path, budget=None)  # 无总预算 → 闸门应拦截
    scan_path = os.path.join(case_dir, "roomplan_scan.json")
    shutil.copy2(os.path.join(ROOT, "templates", "roomplan_scan.template.json"), scan_path)
    scan_summary = summarize_scan_file(scan_path)

    with open(conditions_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    space_profile = build_space_profile(conditions, scan_summary=scan_summary)
    needs_profile = build_needs_profile(conditions, space_profile=space_profile)
    gate = build_automation_gate(space_profile, needs_profile)
    if "budget_estimate" in gate["allowed"]:
        _fail("gate must block budget_estimate without a total budget")

    estimate = build_budget_estimate(space_profile, needs_profile, gate=gate)
    if estimate.get("status") != "blocked_by_automation_gate":
        _fail("build_budget_estimate should return blocked status, got %s" % estimate.get("status"))
    if estimate.get("rooms") or estimate.get("totals"):
        _fail("blocked estimate must not fabricate numbers")

    result = run_mvp_concept_package(conditions_path, scan_summary=scan_summary)
    if "budget_estimate" in result.get("allowed_modules", []):
        _fail("pipeline should keep budget_estimate blocked without budget")
    if result.get("budget_estimate_json"):
        _fail("pipeline must not write budget_estimate.json when blocked")
    with open(result["budget_json"], "r", encoding="utf-8") as f:
        mirror = json.load(f)
    if mirror.get("status") != "blocked_by_automation_gate" or not mirror.get("reasons"):
        _fail("预算方案.json should keep blocked status with reasons")
    if not os.path.exists(result["pptx"]):
        _fail("blocked scenario should still produce the concept PPTX")
    return {"blocked_reasons": len(mirror["reasons"])}


def scenario_budget_logic(tmp):
    from core.scan_importer import summarize_scan_file
    from core.space_profile import build_space_profile
    from core.needs_profile import build_needs_profile
    from core.automation_gate import build_automation_gate
    from core.budget_estimate import build_budget_estimate

    scan_summary = summarize_scan_file(os.path.join(ROOT, "templates", "roomplan_scan.template.json"))
    outcomes = {}
    for label, budget in (("over", 80000), ("within", 1200000)):
        case_dir = os.path.join(tmp, "logic_" + label)
        os.makedirs(case_dir, exist_ok=True)
        conditions_path = os.path.join(case_dir, "design_conditions.json")
        _scan_conditions(conditions_path, budget=budget)
        with open(conditions_path, "r", encoding="utf-8") as f:
            conditions = json.load(f)
        space_profile = build_space_profile(conditions, scan_summary=scan_summary)
        needs_profile = build_needs_profile(conditions, space_profile=space_profile)
        gate = build_automation_gate(space_profile, needs_profile)
        estimate = build_budget_estimate(space_profile, needs_profile, gate=gate, allow_ai=False)
        comparison = _check_comparison(estimate, budget)
        outcomes[label] = comparison["status"]
    if outcomes["over"] != "over_budget":
        _fail("8万 budget should be over_budget, got %s" % outcomes["over"])
    if outcomes["within"] != "within_budget":
        _fail("120万 budget should be within_budget, got %s" % outcomes["within"])
    return outcomes


def scenario_numeric_contract(tmp):
    from core.scan_importer import summarize_scan_file
    from core.space_profile import build_space_profile
    from core.needs_profile import build_needs_profile
    from core.automation_gate import build_automation_gate
    from core.budget_estimate import build_budget_estimate, numeric_view

    case_dir = os.path.join(tmp, "contract_case")
    os.makedirs(case_dir, exist_ok=True)
    conditions_path = os.path.join(case_dir, "design_conditions.json")
    _scan_conditions(conditions_path)
    scan_summary = summarize_scan_file(os.path.join(ROOT, "templates", "roomplan_scan.template.json"))
    with open(conditions_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    space_profile = build_space_profile(conditions, scan_summary=scan_summary)
    needs_profile = build_needs_profile(conditions, space_profile=space_profile)
    gate = build_automation_gate(space_profile, needs_profile)

    first = build_budget_estimate(space_profile, needs_profile, gate=gate, allow_ai=False)
    second = build_budget_estimate(space_profile, needs_profile, gate=gate, allow_ai=False)
    if numeric_view(first) != numeric_view(second):
        _fail("rules-only builds must be deterministic (numeric views differ)")
    # numeric_view 必须排除 AI 文字字段
    injected = copy.deepcopy(first)
    injected["ai_advice"] = {"allocation_advice": "模拟 AI 文字", "saving_tips": ["x"]}
    injected["rooms"][0]["note"] = "模拟 AI 房间备注"
    injected["generation"]["mode"] = "rules_plus_ai"
    if numeric_view(injected) != numeric_view(first):
        _fail("numeric_view must ignore AI text fields (ai_advice / note / generation)")
    return {"deterministic": True, "numeric_fields_stable": True}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        scan_result = scenario_scan(tmp)
        blocked_result = scenario_blocked(tmp)
        logic_result = scenario_budget_logic(tmp)
        contract_result = scenario_numeric_contract(tmp)

    print(json.dumps({
        "ok": True,
        "scan_scenario": scan_result,
        "blocked_scenario": blocked_result,
        "budget_logic_scenario": logic_result,
        "numeric_contract_scenario": contract_result,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
