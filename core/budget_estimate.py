"""M5 budget estimate & material list generation.

Runs only after the M2 automation gate allows ``budget_estimate``. The module
follows the same deterministic-first architecture as M4 (core/layout_draft):
every number (quantities, unit prices, subtotals, totals) is computed by rules
from M0 space facts, the M3 material plan and the configurable price baseline
in ``resources/pricing_baseline.json``. A real LLM, when available, only writes
narrative advice (budget allocation / saving tips) and can never modify any
number — the numeric view is snapshotted before enrichment and verified
unchanged afterwards.

Anti-hallucination contract (same as M3/M4):
- quantities come only from space facts (room area, wall perimeter, openings)
  or transparent default constants, each item records its ``quantity_basis``;
- unit prices come only from the price baseline table, each item records its
  ``unit_price_basis`` (baseline entry + tier, plus the M3 price hint when the
  material plan provides one);
- every inference lands in ``assumptions`` and is prefixed with "假设：";
- no brand names or model numbers anywhere — only material / craft / price tier;
- area follows the input building area; room sums are labelled as such.
"""
import copy
import json
import os
import re

from core.ai_client import get_client
from core.automation_gate import explain_blocked_module
from core.door_access import counts_as_interior_door
from core.layout_draft import extract_room_facts, _room_type


SCHEMA_VERSION = "budget_estimate.v1"
MATERIAL_LIST_VERSION = "material_list.v1"

BASELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "pricing_baseline.json")

CATEGORIES = ["硬装施工", "主材", "家具", "软装", "电器", "全屋项目"]
WET_ROOM_TYPES = {"kitchen", "bathroom", "balcony"}
BEDROOM_TYPES = {"master_bedroom", "bedroom", "kids_room"}

_TIER_ORDER = ["经济档", "标准档", "品质档"]

_baseline_cache = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_pricing_baseline(path=None):
    """Load the configurable price baseline table (cached)."""
    global _baseline_cache
    if path is None:
        if _baseline_cache is not None:
            return _baseline_cache
        path = BASELINE_PATH
    with open(path, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    if path == BASELINE_PATH:
        _baseline_cache = baseline
    return baseline


def build_budget_estimate(space_profile, needs_profile, material_plan=None,
                          layout_draft=None, gate=None, allow_ai=True):
    """Build the M5 budget estimate, or a blocked-status dict.

    All numbers are rule-computed; AI (real mode) only adds ``ai_advice``
    narrative. ``allow_ai=False`` forces the rules-only output (used by the
    numeric-consistency check against the AI-enriched output).
    """
    if gate is not None and "budget_estimate" not in (gate.get("allowed") or []):
        return {
            "status": "blocked_by_automation_gate",
            "module": "budget_estimate",
            "reasons": explain_blocked_module(gate, "budget_estimate") or ["自动化闸门未放行预算估算"],
        }

    space_profile = space_profile or {}
    needs_profile = needs_profile or {}
    baseline = load_pricing_baseline()
    rules = baseline.get("quantity_rules") or {}

    room_facts = extract_room_facts(space_profile, needs_profile)
    if not room_facts:
        return _blocked_insufficient("缺少房间/空间事实，无法计算工程量")
    if not any(_num(r.get("area_m2")) for r in room_facts):
        return _blocked_insufficient("缺少房间面积，无法计算工程量")

    ceiling_known = _ceiling_heights(space_profile)
    layout_draft = layout_draft if (layout_draft or {}).get("status") == "draft" else None
    assumptions = []
    estimate = _build_deterministic_estimate(
        space_profile, needs_profile, material_plan, layout_draft,
        baseline, room_facts, ceiling_known, assumptions)

    client = get_client()
    numeric_before = numeric_view(estimate)
    if client.demo_mode or not allow_ai:
        estimate["demo"] = bool(client.demo_mode)
        estimate["generation"] = {
            "mode": "rules_only_demo" if client.demo_mode else "rules_only",
            "provider": client.provider,
            "warnings": [],
        }
    else:
        warnings = []
        if client.available:
            try:
                _enrich_with_ai(client, estimate, needs_profile)
                mode = "rules_plus_ai"
            except Exception as exc:
                mode = "rules_only_fallback"
                warnings.append(f"AI 文字建议失败，已回退到纯规则预算：{type(exc).__name__}")
        else:
            mode = "rules_only_fallback"
            warnings.append("未配置 AI API Key，预算估算仅含规则引擎输出。")
        estimate["demo"] = False
        estimate["generation"] = {"mode": mode, "provider": client.provider, "warnings": warnings}

    # Numeric contract: AI enrichment must not have changed any number.
    if numeric_view(estimate) != numeric_before:
        estimate.pop("ai_advice", None)
        for room in estimate.get("rooms") or []:
            room.pop("note", None)
        estimate["generation"]["mode"] = "rules_only_fallback"
        estimate["generation"]["warnings"] = (estimate["generation"].get("warnings") or []) + [
            "AI 输出触碰了数字字段，已整段丢弃文字建议（数字以规则引擎为准）。"]
    return estimate


def build_budget_estimate_package(space_profile, needs_profile, material_plan=None,
                                  layout_draft=None, gate=None, output_dir=None):
    """Build the estimate and (when it is a real estimate) write artifacts."""
    estimate = build_budget_estimate(
        space_profile, needs_profile, material_plan=material_plan,
        layout_draft=layout_draft, gate=gate)
    artifacts = {"budget_estimate": None, "material_list": None, "budget_summary_md": None}
    if output_dir and estimate.get("status") == "estimate":
        os.makedirs(output_dir, exist_ok=True)
        material_list = estimate.pop("_material_list")
        json_path = os.path.join(output_dir, "budget_estimate.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(estimate, f, ensure_ascii=False, indent=2)
        list_path = os.path.join(output_dir, "material_list.json")
        with open(list_path, "w", encoding="utf-8") as f:
            json.dump(material_list, f, ensure_ascii=False, indent=2)
        md_path = os.path.join(output_dir, "budget_summary.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(render_budget_summary(estimate, material_list))
        artifacts = {"budget_estimate": json_path, "material_list": list_path,
                     "budget_summary_md": md_path}
        estimate["_material_list"] = material_list
    estimate["artifacts"] = artifacts
    return {"estimate": estimate, **artifacts}


def render_budget_summary(estimate, material_list=None):
    """Human-readable markdown summary of the budget estimate."""
    lines = ["# 预算估算摘要（M5，区间参考价，非报价单）", ""]
    totals = estimate.get("totals") or {}
    comparison = estimate.get("budget_comparison") or {}
    tier = estimate.get("tier") or {}
    baseline_note = estimate.get("price_baseline") or {}
    lines.append(
        "项目：%s；建筑面积：%s㎡；价格档次：%s（%s）；价格基准：%s（%s）。"
        % (
            (estimate.get("project") or {}).get("name") or "未命名项目",
            (estimate.get("project") or {}).get("area_m2") or "未知",
            tier.get("level", ""), tier.get("basis", ""),
            baseline_note.get("source", ""), baseline_note.get("reference", ""),
        ))
    lines.append("")
    lines.append("## 总价区间：%.0f ~ %.0f 元（约 %.1f ~ %.1f 万元）" % (
        totals.get("low", 0), totals.get("high", 0),
        totals.get("low", 0) / 10000, totals.get("high", 0) / 10000))
    if comparison:
        lines.append("")
        lines.append("预算比对：%s" % comparison.get("conclusion", ""))
        for item in comparison.get("overrun_items") or []:
            lines.append("- 主要超支项：%s（%s，上限约 %.0f 元）" % (
                item.get("label", ""), item.get("category", ""), item.get("subtotal_high", 0)))
    lines.append("")
    lines.append("## 分房间小计")
    lines.append("")
    lines.append("| 房间 | 面积(㎡) | 小计区间(元) |")
    lines.append("|------|---------|-------------|")
    for room in estimate.get("rooms") or []:
        lines.append("| %s | %.2f | %.0f ~ %.0f |" % (
            room.get("name", ""), room.get("area_m2", 0),
            room.get("subtotal_low", 0), room.get("subtotal_high", 0)))
    whole = estimate.get("whole_house_items") or []
    if whole:
        lines.append("| 全屋项目 | — | %.0f ~ %.0f |" % (
            sum(_num(i.get("subtotal_low")) for i in whole),
            sum(_num(i.get("subtotal_high")) for i in whole)))
    lines.append("")
    lines.append("## 分项明细（工程量来源透明可查）")
    for room in estimate.get("rooms") or []:
        lines.append("")
        lines.append("### %s" % room.get("name", ""))
        for item in room.get("items") or []:
            lines.append("- 【%s】%s：%.2f%s × %.0f~%.0f 元 = %.0f~%.0f 元（工程量：%s；单价：%s）" % (
                item.get("category", ""), item.get("item", ""),
                item.get("quantity", 0), item.get("unit", ""),
                item.get("unit_price_low", 0), item.get("unit_price_high", 0),
                item.get("subtotal_low", 0), item.get("subtotal_high", 0),
                item.get("quantity_basis", ""), item.get("unit_price_basis", "")))
    if whole:
        lines.append("")
        lines.append("### 全屋项目")
        for item in whole:
            lines.append("- 【%s】%s：%.2f%s × %.0f~%.0f 元 = %.0f~%.0f 元（工程量：%s；单价：%s）" % (
                item.get("category", ""), item.get("item", ""),
                item.get("quantity", 0), item.get("unit", ""),
                item.get("unit_price_low", 0), item.get("unit_price_high", 0),
                item.get("subtotal_low", 0), item.get("subtotal_high", 0),
                item.get("quantity_basis", ""), item.get("unit_price_basis", "")))
    if material_list:
        lines.append("")
        lines.append("## 全屋主材清单（用量估算）")
        lines.append("")
        lines.append("| 材料 | 用量 | 单位 | 价位档 | 用量来源 |")
        lines.append("|------|------|------|--------|---------|")
        for item in material_list.get("items") or []:
            lines.append("| %s | %.2f | %s | %s | %s |" % (
                item.get("material", ""), item.get("quantity", 0), item.get("unit", ""),
                item.get("tier", ""), item.get("quantity_basis", "")))
    advice = estimate.get("ai_advice") or {}
    if advice.get("allocation_advice"):
        lines.append("")
        lines.append("## AI 预算分配建议（文字建议，不改动任何数字）")
        lines.append(advice["allocation_advice"])
        for tip in advice.get("saving_tips") or []:
            lines.append("- %s" % tip)
    lines.append("")
    lines.append("## 假设与不确定项（须设计师复核）")
    for item in estimate.get("assumptions") or []:
        lines.append("- %s" % item)
    lines.append("")
    return "\n".join(lines)


def numeric_view(estimate):
    """The number-carrying view of an estimate, stripped of all AI text fields.

    Two estimates with the same numeric_view are numerically identical; used to
    prove the AI-enriched run never modified a number. ``assumptions`` is
    excluded because AI enrichment may append extra (purely textual, always
    「假设：」-prefixed) inferred assumptions; it never touches numbers.
    """
    skip_keys = {"ai_advice", "generation", "demo", "artifacts", "_material_list",
                 "note", "assumptions"}
    def _clean(node):
        if isinstance(node, dict):
            return {k: _clean(v) for k, v in sorted(node.items()) if k not in skip_keys}
        if isinstance(node, list):
            return [_clean(v) for v in node]
        return node
    return _clean(copy.deepcopy(estimate or {}))


# ---------------------------------------------------------------------------
# Deterministic estimate
# ---------------------------------------------------------------------------

def _build_deterministic_estimate(space_profile, needs_profile, material_plan,
                                  layout_draft, baseline, room_facts,
                                  ceiling_known, assumptions):
    project = (space_profile.get("project") or {})
    geometry = (space_profile.get("geometry") or {})
    tier, tier_basis = _resolve_tier(needs_profile, project, baseline)

    material_map, material_defaults = _room_material_map(material_plan, room_facts, needs_profile)
    if material_defaults:
        assumptions.append(_assumption(
            "以下房间未在 M3 材质方案中覆盖，按房型默认材质估算：%s；需设计师复核。"
            % "、".join(material_defaults)))

    layout_furniture = _layout_furniture_by_room(layout_draft)
    if not layout_draft:
        assumptions.append(_assumption(
            "未生成布局草案（或草案被闸门拦截），家具/柜体工程量按房型标准配置估算，数量与尺寸需设计师复核。"))

    if any(not ceiling_known.get(r["name"]) for r in room_facts):
        default_h = int(_num((baseline.get("quantity_rules") or {}).get("default_ceiling_height_mm")) or 2700)
        assumptions.append(_assumption(
            "部分房间层高未在输入中提供，墙面/顶面工程量按层高 %dmm 估算。" % default_h))

    rooms_out = []
    quantity_facts = {}
    for facts in room_facts:
        room_out, qfacts = _estimate_room(
            facts, material_map, layout_furniture, baseline, tier,
            ceiling_known, needs_profile, assumptions)
        rooms_out.append(room_out)
        quantity_facts[facts["name"]] = qfacts

    whole_items = _whole_house_items(
        space_profile, room_facts, quantity_facts, baseline, tier, assumptions)

    totals = _compute_totals(rooms_out, whole_items)
    comparison = _budget_comparison(needs_profile, project, totals, rooms_out, whole_items)

    assumptions.append(_assumption(
        "价格来自《装修价格基准表》2026 年参考价位档（全国二线中位水平），仅为前期提案区间估算；设计师须按当地市场校准后才能对客户报价。"))
    if project.get("area_m2"):
        assumptions.append(_assumption(
            "面积口径以输入建筑面积 %s㎡ 为准；各房间工程量按空间事实中的房间尺寸计算，加总与建面差异属公摊/墙体口径差。"
            % project["area_m2"]))
    assumptions.append(_assumption(
        "拆除/旧改、结构改动与个性化造型吊顶未计入（输入未标明相关需求），如有发生需另行估算。"))

    estimate = {
        "schema_version": SCHEMA_VERSION,
        "status": "estimate",
        "module": "budget_estimate",
        "currency": "CNY",
        "project": {
            "name": project.get("name", ""),
            "house_type": project.get("house_type", ""),
            "area_m2": project.get("area_m2"),
        },
        "price_baseline": {
            "source": "resources/pricing_baseline.json",
            "version": (baseline.get("_meta") or {}).get("version", ""),
            "reference": "2026 年参考价位档，需设计师按当地市场校准",
        },
        "tier": {"level": tier, "basis": tier_basis},
        "source_facts": {
            "geometry_source": geometry.get("source_type", ""),
            "geometry_confidence": geometry.get("confidence"),
            "room_count": len(room_facts),
            "has_layout_draft": bool(layout_draft),
        },
        "rooms": rooms_out,
        "whole_house_items": whole_items,
        "totals": totals,
        "budget_comparison": comparison,
        "assumptions": assumptions,
    }
    estimate["_material_list"] = _build_material_list(quantity_facts, baseline, tier)
    return estimate


def _counts_as_interior_door(op):
    """室内门工程量口径——统一收口到 core.door_access（单一口径定义点）。

    保留本包装仅为兼容既有导入（验收脚本等）；语义以
    door_access.counts_as_interior_door 为准，布局摘要门数同源。
    """
    return counts_as_interior_door(op)


def _estimate_room(facts, material_map, layout_furniture, baseline, tier,
                   ceiling_known, needs_profile, assumptions):
    """Rule-computed line items for one room. Returns (room_out, quantity_facts)."""
    name = facts["name"]
    rtype = _room_type(facts)
    rules = baseline.get("quantity_rules") or {}
    area = round(_num(facts.get("area_m2")), 2)
    width_m = _num(facts.get("width_mm")) / 1000
    length_m = _num(facts.get("length_mm")) / 1000
    perimeter_m = 2 * (width_m + length_m) if width_m and length_m else 0
    ceiling_mm = ceiling_known.get(name) or int(_num(rules.get("default_ceiling_height_mm")) or 2700)
    ceiling_m = ceiling_mm / 1000

    openings = [o for wall in facts.get("walls") or [] for o in wall.get("openings") or []]
    opening_area = 0.0
    opening_notes = []
    for op in openings:
        ow = _num(op.get("width_mm")) / 1000
        oh = _num(op.get("height_mm")) / 1000
        if not oh:
            oh = _num(rules.get("default_door_height_mm" if op.get("kind") == "door"
                                else "default_window_height_mm")) / 1000
        opening_area += ow * oh
        opening_notes.append("%s %.1f㎡" % ("门洞" if op.get("kind") == "door" else "窗", ow * oh))
    wall_gross = perimeter_m * ceiling_m
    wall_net = max(0.0, wall_gross - opening_area)

    req_text = " ".join(str(v) for v in (facts.get("requirements") or {}).values())
    materials = material_map.get(name) or {}
    wet = rtype in WET_ROOM_TYPES

    floor_mat = _material_for(materials, "floor", rtype, needs_profile, "floor")
    wall_mat = _material_for(materials, "wall", rtype, needs_profile, "wall")
    ceil_mat = _material_for(materials, "ceiling", rtype, needs_profile, "ceiling")

    qfacts = {
        "room_type": rtype,
        "area_m2": area,
        "wall_area_m2": round(wall_net, 2),
        "ceiling_area_m2": area,
        "floor_material": floor_mat["name"],
        "wall_material": wall_mat["name"],
        "ceiling_material": ceil_mat["name"],
        "wet": wet,
        "has_window": any(op.get("kind") == "window" for op in openings),
        "custom_cabinet_m2": 0.0,
        "kitchen_counter_m": 0.0,
        "door_count": sum(1 for op in openings if _counts_as_interior_door(op)),
        "door_openings_skipped": sum(1 for op in openings
                                     if op.get("kind") == "door"
                                     and not _counts_as_interior_door(op)),
    }

    items = []

    def add(category, entry_name, quantity, unit, quantity_basis, extra_price_basis=""):
        if quantity <= 0:
            return None
        item = _make_item(baseline, category, entry_name, tier, quantity, unit,
                          quantity_basis, extra_price_basis)
        if item:
            items.append(item)
        return item

    # 1) 硬装施工（人工+辅料）
    add("硬装施工", "地面工程（人工+辅料）", area, "㎡",
        "地面面积=房间面积 %.2f㎡" % area)
    wall_basis = "墙面面积=周长 %.2fm × 层高 %.1fm − 开口(%s) = %.2f㎡" % (
        perimeter_m, ceiling_m, "、".join(opening_notes) or "无", wall_net)
    add("硬装施工", "墙面工程（人工+辅料）", round(wall_net, 2), "㎡", wall_basis)
    add("硬装施工", "顶面工程（人工+辅料）", area, "㎡",
        "顶面面积=房间面积 %.2f㎡" % area)

    # 2) 主材
    add("主材", floor_mat["entry"], area, "㎡",
        "地面面积=房间面积 %.2f㎡（损耗在材料清单中另计）" % area, floor_mat.get("hint", ""))
    add("主材", wall_mat["entry"], round(wall_net, 2), "㎡", wall_basis, wall_mat.get("hint", ""))
    add("主材", ceil_mat["entry"], area, "㎡",
        "顶面面积=房间面积 %.2f㎡" % area, ceil_mat.get("hint", ""))

    # 家具布局 → 定制柜体 / 橱柜 / 卫浴 / 电器 / 成品家具
    furniture = layout_furniture.get(name)
    if furniture is None:
        furniture = _fallback_furniture(rtype)
        for f in furniture:
            f["from_fallback"] = True
    _items_from_furniture(furniture, add, qfacts, baseline, tier, rules,
                          assumptions, name, wet, req_text)

    # 卫浴（按房型固定计）
    if rtype == "bathroom":
        add("主材", "卫浴洁具套组", 1, "套", "卫生间 1 间 × 1 套（浴室柜+马桶+花洒）")
        if "干湿分离" in req_text or any("隔断" in (f.get("item") or "") for f in furniture):
            add("主材", "淋浴隔断", 1, "套", "需求含干湿分离，按 1 套玻璃隔断计")

    # 3) 软装
    if qfacts["has_window"]:
        add("软装", "窗帘（含轨道）", 1, "间", "房间有窗户，按 1 间计")
    add("软装", "灯具组合", 1, "间", "按 1 间 1 套基础灯具计")
    if rtype in BEDROOM_TYPES:
        add("软装", "床品布艺", 1, "间", "卧室按 1 间计")

    # 4) 电器（按房型与需求关键词）
    _appliance_items(rtype, req_text, furniture, add)

    room_out = {
        "name": name,
        "room_type": rtype,
        "area_m2": area,
        "items": items,
        "subtotal_low": _money(sum(_num(i["subtotal_low"]) for i in items)),
        "subtotal_high": _money(sum(_num(i["subtotal_high"]) for i in items)),
    }
    return room_out, qfacts


def _items_from_furniture(furniture, add, qfacts, baseline, tier, rules,
                          assumptions, room_name, wet, req_text):
    """Translate layout/fallback furniture into priced line items."""
    cabinet_h = _num(rules.get("custom_cabinet_height_mm")) or 2400
    for f in furniture or []:
        item_name = f.get("item") or ""
        width_mm = _num(f.get("width_mm"))
        if not item_name:
            continue
        fallback_note = "（标准配置估算）" if f.get("from_fallback") else ""
        if "整墙衣柜" in item_name or item_name.startswith("衣柜") or item_name in ("收纳柜",):
            proj = round(width_mm / 1000 * cabinet_h / 1000, 2)
            add("主材", "定制柜体（投影面积）", proj, "㎡",
                "投影面积=%s宽度 %dmm × 假设柜高 %dmm = %.2f㎡%s"
                % (item_name, int(width_mm), int(cabinet_h), proj, fallback_note))
            qfacts["custom_cabinet_m2"] += proj
        elif "整体橱柜" in item_name:
            counter_m = round(width_mm / 1000, 2)
            add("主材", "整体橱柜", counter_m, "延米",
                "延米=布局橱柜长度 %dmm ÷ 1000 = %.2f 延米%s" % (int(width_mm), counter_m, fallback_note))
            qfacts["kitchen_counter_m"] = counter_m
        elif "冰箱" in item_name:
            add("电器", "冰箱", 1, "台", "布局含冰箱位，按 1 台计")
        elif "洗碗机" in item_name:
            add("电器", "洗碗机", 1, "台", "需求/布局含洗碗机位，按 1 台计")
        elif "大单槽" in item_name or "马桶区" in item_name:
            continue  # 并入整体橱柜 / 卫浴洁具套组，不重复计
        elif "淋浴区" in item_name:
            continue  # 隔断在干湿分离判断中另计
        elif "洗衣/储物" in item_name:
            continue  # 家政区非固定柜体，洗衣机在电器中计
        else:
            entry = _match_entry(baseline, "家具", item_name) or "其他家具"
            add("家具", entry, 1, "件",
                "布局家具「%s」按 1 件计%s" % (item_name, fallback_note))


def _fallback_furniture(rtype):
    """Standard furniture package per room type when no layout draft exists."""
    def f(item, width):
        return {"item": item, "width_mm": width, "depth_mm": 0}
    packages = {
        "living": [f("三人沙发", 2400), f("电视柜", 2200), f("茶几", 1200)],
        "master_bedroom": [f("双人床", 1800), f("床头柜", 500), f("衣柜", 1800)],
        "bedroom": [f("单人床", 1500), f("床头柜", 500), f("衣柜", 1800)],
        "kids_room": [f("单人床", 1200), f("床头柜", 500), f("书桌", 1200), f("衣柜", 1800)],
        "study": [f("书桌", 1400), f("书柜", 1600)],
        "kitchen": [f("整体橱柜（地柜+吊柜）", 3000)],
        "dining": [f("餐桌", 1400), f("餐边柜", 1400)],
        "entry": [f("鞋柜", 1200)],
        "bathroom": [f("浴室柜", 900)],
        "balcony": [],
        "generic": [f("收纳柜", 1200)],
    }
    return [dict(item) for item in packages.get(rtype, packages["generic"])]


def _appliance_items(rtype, req_text, furniture, add):
    furniture_names = " ".join(f.get("item") or "" for f in furniture or [])
    if rtype == "kitchen":
        if "冰箱" not in furniture_names:
            add("电器", "冰箱", 1, "台", "厨房标配，按 1 台计")
        add("电器", "烟灶套装", 1, "套", "厨房标配，按 1 套计")
        if "洗碗机" in req_text and "洗碗机" not in furniture_names:
            add("电器", "洗碗机", 1, "台", "需求含洗碗机，按 1 台计")
    elif rtype == "bathroom":
        add("电器", "燃气热水器", 1, "台", "卫生间标配，按 1 台计")
    elif rtype == "balcony":
        add("电器", "洗衣机", 1, "台", "阳台家政区，按 1 台计")
    elif rtype == "living":
        add("电器", "电视机", 1, "台", "客厅观影需求，按 1 台计")
        add("电器", "空调（柜机）", 1, "台", "客厅按 1 台柜机计")
    elif rtype in BEDROOM_TYPES or rtype == "study":
        add("电器", "空调（挂机）", 1, "台", "房间按 1 台挂机计")


def _whole_house_items(space_profile, room_facts, quantity_facts, baseline, tier, assumptions):
    whole = baseline.get("whole_house") or {}
    room_total = round(sum(q["area_m2"] for q in quantity_facts.values()), 2)
    building_area = _num((space_profile.get("project") or {}).get("area_m2"))
    items = []

    def add(entry_name, quantity, quantity_basis):
        entry = whole.get(entry_name) or {}
        tiers = entry.get("tiers") or {}
        low, high = (tiers.get(tier) or tiers.get("标准档") or [0, 0])
        quantity = round(quantity, 2)
        items.append({
            "category": "全屋项目",
            "item": entry_name,
            "quantity": quantity,
            "unit": entry.get("unit", "项"),
            "quantity_basis": quantity_basis,
            "unit_price_low": _money(low),
            "unit_price_high": _money(high),
            "unit_price_basis": "基准表·全屋项目/%s·%s" % (entry_name, tier),
            "subtotal_low": _money(quantity * low),
            "subtotal_high": _money(quantity * high),
        })

    add("水电改造", room_total, "计费面积=各房间面积加总 %.2f㎡" % room_total)
    add("垃圾清运与成品保护", room_total, "计费面积=各房间面积加总 %.2f㎡" % room_total)
    if building_area:
        add("设计费", building_area, "计费面积=输入建筑面积 %.2f㎡" % building_area)
    else:
        add("设计费", room_total, "计费面积=各房间面积加总 %.2f㎡（输入未提供建筑面积）" % room_total)

    # 室内门：按空间事实中的门洞数量（经门语义分级过滤，超宽/未证实洞口不计）
    door_total = sum(q.get("door_count", 0) for q in quantity_facts.values())
    door_skipped = sum(q.get("door_openings_skipped", 0) for q in quantity_facts.values())
    if door_skipped:
        assumptions.append(_assumption(
            "%d 个超宽（>1.2m）或未证实洞口未计入室内门工程量（推拉门/垭口/飘窗面"
            "或疑似误判均不需采购室内门），需设计师按现场确认后另行估算。" % door_skipped))
    if door_total:
        entry = (baseline.get("unit_prices") or {}).get("主材", {}).get("室内门（含门套）") or {}
        low, high = (entry.get("tiers") or {}).get(tier) or [0, 0]
        items.append({
            "category": "主材",
            "item": "室内门（含门套）",
            "quantity": door_total,
            "unit": "樘",
            "quantity_basis": "门数量=空间事实中有门扇证据的门+门洞量级（≤1.2m）洞口共 %d 樘"
            "（含套线；入户门、超宽垭口/推拉门与未证实洞口未计入）" % door_total,
            "unit_price_low": _money(low),
            "unit_price_high": _money(high),
            "unit_price_basis": "基准表·主材/室内门（含门套）·%s" % tier,
            "subtotal_low": _money(door_total * low),
            "subtotal_high": _money(door_total * high),
        })
    else:
        assumptions.append(_assumption("空间事实中无门洞记录，室内门未计入预算，需设计师按实际补齐。"))

    # 综合管理费：费率在 _compute_totals 中按全量硬装施工+主材小计计取
    mgmt = whole.get("综合管理费") or {}
    rate = mgmt.get("rate") or [0.05, 0.08]
    items.append({
        "category": "全屋项目",
        "item": "综合管理费",
        "quantity": 1,
        "unit": "项",
        "quantity_basis": "费率计取项，基数与金额在合计时计算",
        "unit_price_low": 0.0,  # placeholder, computed in _compute_totals
        "unit_price_high": 0.0,
        "unit_price_basis": "基准表·全屋项目/综合管理费·费率 %.2f~%.2f" % (rate[0], rate[1]),
        "subtotal_low": 0.0,
        "subtotal_high": 0.0,
        "_rate": rate,
    })
    return items


def _compute_totals(rooms_out, whole_items):
    # 综合管理费基数 = 全部分项的硬装施工+主材（含房间级）
    rate = [0.05, 0.08]
    mgmt_item = None
    for item in whole_items:
        if item.get("item") == "综合管理费" and item.get("_rate"):
            rate = item["_rate"]
            mgmt_item = item
    base_low = sum(_num(i["subtotal_low"]) for r in rooms_out for i in r["items"]
                   if i["category"] in ("硬装施工", "主材"))
    base_high = sum(_num(i["subtotal_high"]) for r in rooms_out for i in r["items"]
                    if i["category"] in ("硬装施工", "主材"))
    base_low += sum(_num(i["subtotal_low"]) for i in whole_items
                    if i["category"] in ("硬装施工", "主材"))
    base_high += sum(_num(i["subtotal_high"]) for i in whole_items
                     if i["category"] in ("硬装施工", "主材"))
    if mgmt_item is not None:
        mgmt_item.pop("_rate", None)
        mgmt_item["quantity_basis"] = (
            "按硬装施工与主材小计的 %.0f%%~%.0f%% 计取（基数 %.0f~%.0f 元）"
            % (rate[0] * 100, rate[1] * 100, base_low, base_high))
        mgmt_item["unit_price_low"] = _money(base_low * rate[0])
        mgmt_item["unit_price_high"] = _money(base_high * rate[1])
        mgmt_item["subtotal_low"] = _money(base_low * rate[0])
        mgmt_item["subtotal_high"] = _money(base_high * rate[1])

    by_category = {}
    for cat in CATEGORIES:
        low = sum(_num(i["subtotal_low"]) for r in rooms_out for i in r["items"] if i["category"] == cat)
        high = sum(_num(i["subtotal_high"]) for r in rooms_out for i in r["items"] if i["category"] == cat)
        low += sum(_num(i["subtotal_low"]) for i in whole_items if i["category"] == cat)
        high += sum(_num(i["subtotal_high"]) for i in whole_items if i["category"] == cat)
        if low or high:
            by_category[cat] = {"low": _money(low), "high": _money(high)}
    total_low = _money(sum(v["low"] for v in by_category.values()))
    total_high = _money(sum(v["high"] for v in by_category.values()))
    return {"low": total_low, "high": total_high, "by_category": by_category}


def _budget_comparison(needs_profile, project, totals, rooms_out, whole_items):
    budget = _num(((needs_profile or {}).get("budget") or {}).get("total_budget"))
    comparison = {
        "user_budget": budget or None,
        "total_low": totals["low"],
        "total_high": totals["high"],
        "status": "no_user_budget",
        "conclusion": "业主未提供总预算，无法比对；以上区间为规则估算参考。",
        "overrun_items": [],
    }
    if not budget:
        return comparison
    if totals["high"] <= budget:
        status = "within_budget"
        conclusion = ("总预算区间上限 %.0f 元 ≤ 业主预算 %.0f 元，在预算内（富余 %.0f 元）。"
                      % (totals["high"], budget, budget - totals["high"]))
    elif totals["low"] <= budget:
        status = "risk_of_overrun"
        conclusion = ("预算区间 %.0f~%.0f 元跨业主预算 %.0f 元，上限超出 %.0f 元，存在超支风险；建议按下限口径控制主材与家具档次。"
                      % (totals["low"], totals["high"], budget, totals["high"] - budget))
    else:
        status = "over_budget"
        conclusion = ("预算区间下限 %.0f 元已超业主预算 %.0f 元（超出 %.0f 元），明显超支；需整体下调档次或缩减项目。"
                      % (totals["low"], budget, totals["low"] - budget))
    overruns = []
    if status != "within_budget":
        all_items = [("%s·%s" % (r["name"], i["item"]), i)
                     for r in rooms_out for i in r["items"]]
        all_items += [("全屋·%s" % i["item"], i) for i in whole_items]
        all_items.sort(key=lambda pair: _num(pair[1]["subtotal_high"]), reverse=True)
        for label, i in all_items[:3]:
            overruns.append({
                "label": label,
                "category": i["category"],
                "subtotal_high": i["subtotal_high"],
            })
    comparison.update({"status": status, "conclusion": conclusion, "overrun_items": overruns})
    return comparison


# ---------------------------------------------------------------------------
# Material list
# ---------------------------------------------------------------------------

def _build_material_list(quantity_facts, baseline, tier):
    rules = baseline.get("quantity_rules") or {}
    floor_wastage = _num(rules.get("floor_wastage")) or 1.05
    tile_wastage = _num(rules.get("tile_wastage")) or 1.08

    buckets = {}  # (material, entry, unit) -> {quantity, basis_parts}
    def bucket(material, entry, unit, quantity, basis):
        key = (material, entry, unit)
        slot = buckets.setdefault(key, {"quantity": 0.0, "basis": []})
        slot["quantity"] += quantity
        slot["basis"].append(basis)

    for name, q in quantity_facts.items():
        if q["wet"]:
            floor_qty = round(q["area_m2"] * tile_wastage, 2)
            bucket(q["floor_material"], "瓷砖（地砖）", "㎡", floor_qty,
                   "%s地面 %.2f㎡ × 损耗 %.2f" % (name, q["area_m2"], tile_wastage))
            wall_qty = round(q["wall_area_m2"] * tile_wastage, 2)
            bucket(q["wall_material"], "厨卫墙砖", "㎡", wall_qty,
                   "%s墙面 %.2f㎡ × 损耗 %.2f" % (name, q["wall_area_m2"], tile_wastage))
            bucket(q["ceiling_material"], "铝扣板吊顶", "㎡", q["ceiling_area_m2"],
                   "%s顶面 %.2f㎡" % (name, q["ceiling_area_m2"]))
        else:
            floor_entry = _match_entry(baseline, "主材", q["floor_material"]) or "实木复合地板"
            floor_qty = round(q["area_m2"] * floor_wastage, 2)
            bucket(q["floor_material"], floor_entry, "㎡", floor_qty,
                   "%s地面 %.2f㎡ × 损耗 %.2f" % (name, q["area_m2"], floor_wastage))
            wall_entry = _match_entry(baseline, "主材", q["wall_material"]) or "乳胶漆"
            bucket(q["wall_material"] + "（墙面）", wall_entry, "㎡", q["wall_area_m2"],
                   "%s墙面 %.2f㎡" % (name, q["wall_area_m2"]))
            ceil_entry = _match_entry(baseline, "主材", q["ceiling_material"]) or "乳胶漆"
            bucket(q["ceiling_material"] + "（顶面）", ceil_entry, "㎡", q["ceiling_area_m2"],
                   "%s顶面 %.2f㎡" % (name, q["ceiling_area_m2"]))
        if q.get("custom_cabinet_m2"):
            bucket("定制柜体板材", "定制柜体（投影面积）", "㎡", round(q["custom_cabinet_m2"], 2),
                   "%s定制柜体投影 %.2f㎡" % (name, q["custom_cabinet_m2"]))
        if q.get("kitchen_counter_m"):
            bucket("整体橱柜", "整体橱柜", "延米", q["kitchen_counter_m"],
                   "%s橱柜 %.2f 延米" % (name, q["kitchen_counter_m"]))

    items = []
    merged = {}  # (entry, unit) -> {material, quantity, basis}
    for (material, entry, unit), slot in buckets.items():
        key = (entry, unit)
        slot_m = merged.setdefault(key, {"material": entry, "quantity": 0.0, "basis": []})
        slot_m["quantity"] += slot["quantity"]
        slot_m["basis"].extend(slot["basis"])
    for (entry, unit), slot in merged.items():
        low, high = _entry_price(baseline, _category_of_entry(baseline, entry), entry, tier)
        items.append({
            "material": slot["material"],
            "baseline_entry": entry,
            "quantity": _money(slot["quantity"]),
            "unit": unit,
            "quantity_basis": "；".join(slot["basis"]),
            "tier": tier,
            "unit_price_low": _money(low),
            "unit_price_high": _money(high),
            "price_basis": "基准表·主材/%s·%s（2026 年参考价位档）" % (entry, tier),
        })
    items.sort(key=lambda i: -i["quantity"] * i["unit_price_high"])

    door_total = sum(q.get("door_count", 0) for q in quantity_facts.values())
    if door_total:
        low, high = _entry_price(baseline, "主材", "室内门（含门套）", tier)
        items.append({
            "material": "室内门（含门套）",
            "baseline_entry": "室内门（含门套）",
            "quantity": door_total,
            "unit": "樘",
            "quantity_basis": "空间事实中有门扇证据的门+门洞量级（≤1.2m）洞口共 %d 樘" % door_total,
            "tier": tier,
            "unit_price_low": _money(low),
            "unit_price_high": _money(high),
            "price_basis": "基准表·主材/室内门（含门套）·%s（2026 年参考价位档）" % tier,
        })

    bath_count = sum(1 for q in quantity_facts.values() if q["room_type"] == "bathroom")
    if bath_count:
        low, high = _entry_price(baseline, "主材", "卫浴洁具套组", tier)
        items.append({
            "material": "卫浴洁具套组",
            "baseline_entry": "卫浴洁具套组",
            "quantity": bath_count,
            "unit": "套",
            "quantity_basis": "卫生间 %d 间 × 1 套" % bath_count,
            "tier": tier,
            "unit_price_low": _money(low),
            "unit_price_high": _money(high),
            "price_basis": "基准表·主材/卫浴洁具套组·%s（2026 年参考价位档）" % tier,
        })

    return {
        "schema_version": MATERIAL_LIST_VERSION,
        "module": "material_list",
        "tier": tier,
        "items": items,
        "assumptions": [
            "假设：主材用量含损耗系数（地面 ×%.2f、瓷砖/墙砖 ×%.2f），实际下料以施工方排版图为准。" % (floor_wastage, tile_wastage),
            "假设：价格为 2026 年参考价位档，需设计师按当地市场与品牌选择校准。",
        ],
    }


# ---------------------------------------------------------------------------
# Price / material resolution helpers
# ---------------------------------------------------------------------------

def _resolve_tier(needs_profile, project, baseline):
    thresholds = baseline.get("tier_thresholds_per_m2") or {}
    economic_below = _num(thresholds.get("economic_below")) or 2500
    premium_above = _num(thresholds.get("premium_above")) or 4500
    budget = _num(((needs_profile or {}).get("budget") or {}).get("total_budget"))
    area = _num((project or {}).get("area_m2"))
    if budget and area:
        per_m2 = budget / area
        if per_m2 < economic_below:
            tier = "经济档"
        elif per_m2 > premium_above:
            tier = "品质档"
        else:
            tier = "标准档"
        return tier, ("总预算 %.0f 元 ÷ 建筑面积 %.2f㎡ = %.0f 元/㎡，按基准表阈值（<%.0f 经济档 / >%.0f 品质档）判定为%s"
                      % (budget, area, per_m2, economic_below, premium_above, tier))
    return "标准档", "缺少总预算或建筑面积，默认按标准档估算"


def _room_material_map(material_plan, room_facts, needs_profile):
    """Map each room to its M3 material choices; rooms missing from M3 use defaults."""
    plan_by_room = {}
    for entry in (material_plan or {}).get("materials") or []:
        if isinstance(entry, dict) and entry.get("room"):
            plan_by_room[entry["room"]] = entry
    style = (needs_profile or {}).get("style_preferences") or {}
    result = {}
    defaults = []
    for facts in room_facts:
        name = facts["name"]
        plan = plan_by_room.get(name)
        if plan:
            result[name] = {
                "floor": (plan.get("floor") or {}),
                "wall": (plan.get("wall") or {}),
                "ceiling": (plan.get("ceiling") or {}),
            }
        else:
            defaults.append(name)
            result[name] = {
                "floor": {"type": style.get("floor_material") or ""},
                "wall": {"type": style.get("wall_material") or ""},
                "ceiling": {"type": ""},
            }
    return result, defaults


def _material_for(materials, slot, rtype, needs_profile, part):
    """Resolve the baseline entry + price hint for a room's floor/wall/ceiling."""
    wet = rtype in WET_ROOM_TYPES
    raw = (materials.get(slot) or {})
    type_text = (raw.get("type") or "").strip()
    hint = _price_hint(raw.get("code") or "")
    if not type_text:
        if part == "floor":
            type_text = "瓷砖" if wet else "实木复合地板"
        elif part == "wall":
            type_text = "厨卫墙砖" if wet else "乳胶漆"
        else:
            type_text = "铝扣板吊顶" if wet else "乳胶漆"
    if wet:
        # 湿区强制安全默认：地面砖、墙面砖、顶面铝扣板（M3 若给出其他也尊重，但砖类优先匹配）
        pass
    entry = _match_entry(load_pricing_baseline(), "主材", type_text)
    if not entry:
        entry = {"floor": "实木复合地板", "wall": "乳胶漆", "ceiling": "乳胶漆"}[part]
        if wet:
            entry = {"floor": "瓷砖（地砖）", "wall": "厨卫墙砖", "ceiling": "铝扣板吊顶"}[part]
    return {"name": type_text, "entry": entry, "hint": hint}


def _price_hint(code):
    """Extract an M3 price hint like 约220元/㎡（ENF级） for the basis text."""
    text = str(code or "").strip()
    if not text or text == "demo":
        return ""
    match = re.search(r"(约?\d+(?:\.\d+)?\s*元\s*/\s*(?:㎡|m2|平|延米|樘|套)[^，,;；]*)", text)
    if match:
        return "M3价位档参考：%s" % match.group(1)
    if re.search(r"\d", text) and "元" in text:
        return "M3价位档参考：%s" % text
    return ""


def _match_entry(baseline, category, text):
    """Match a material/furniture name to a baseline entry via keywords."""
    entries = (baseline.get("unit_prices") or {}).get(category) or {}
    text = str(text or "")
    if not text:
        return None
    if text in entries:
        return text
    best = None
    best_len = 0
    for entry_name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        for kw in entry.get("keywords") or []:
            if kw and kw in text and len(kw) > best_len:
                best = entry_name
                best_len = len(kw)
    return best


def _category_of_entry(baseline, entry_name):
    for category, entries in (baseline.get("unit_prices") or {}).items():
        if entry_name in entries:
            return category
    return "主材"


def _entry_price(baseline, category, entry_name, tier):
    entries = (baseline.get("unit_prices") or {}).get(category) or {}
    entry = entries.get(entry_name) or {}
    low, high = (entry.get("tiers") or {}).get(tier) or \
        (entry.get("tiers") or {}).get("标准档") or [0, 0]
    return low, high


def _make_item(baseline, category, entry_name, tier, quantity, unit,
               quantity_basis, extra_price_basis=""):
    low, high = _entry_price(baseline, category, entry_name, tier)
    if not (low or high):
        return None
    quantity = round(quantity, 2)
    price_basis = "基准表·%s/%s·%s" % (category, entry_name, tier)
    if extra_price_basis:
        price_basis += "；" + extra_price_basis
    return {
        "category": category,
        "item": entry_name,
        "quantity": quantity,
        "unit": unit,
        "quantity_basis": quantity_basis,
        "unit_price_low": _money(low),
        "unit_price_high": _money(high),
        "unit_price_basis": price_basis,
        "subtotal_low": _money(quantity * low),
        "subtotal_high": _money(quantity * high),
    }


def _layout_furniture_by_room(layout_draft):
    result = {}
    for room in (layout_draft or {}).get("rooms") or []:
        if room.get("name"):
            result[room["name"]] = room.get("furniture") or []
    return result


def _ceiling_heights(space_profile):
    result = {}
    for room in ((space_profile or {}).get("geometry") or {}).get("rooms") or []:
        if room.get("name"):
            result[room["name"]] = int(_num(room.get("ceiling_height_mm")) or 0)
    return result


# ---------------------------------------------------------------------------
# AI enrichment (real mode only; narrative only, numbers are frozen)
# ---------------------------------------------------------------------------

_ENRICH_SYSTEM_PROMPT = """你是资深室内设计预算顾问。下面是一份由规则引擎生成的装修预算区间 JSON（所有数字已由确定性规则计算完毕，禁止改动）。
请只输出文字建议 JSON：
{
  "allocation_advice": "预算分配建议，≤150字，结合总价区间与业主预算给出大类分配取舍",
  "saving_tips": ["省钱建议，每条≤40字，3-5条，必须结合具体房间或分项"],
  "room_notes": [{"name": "房间名（必须与输入完全一致）", "note": "该房间预算要点，≤60字"}],
  "extra_assumptions": ["仅当引入了输入之外的推断时填写，且必须以\\"假设：\\"开头"]
}

【数字红线 — 必须严格遵守】
1. 禁止修改、新增或删除任何金额、数量、单价；输出文字中不得出现具体金额数字，引用金额一律写「见预算表」。
2. 禁止编造品牌与型号；只能讨论材质档次/工艺/品类层面的取舍。
3. room_notes 的 name 必须逐字匹配输入房间名；推断只能放入 extra_assumptions 且以"假设："开头。"""


def _enrich_with_ai(client, estimate, needs_profile):
    totals = estimate.get("totals") or {}
    comparison = estimate.get("budget_comparison") or {}
    payload = {
        "project": estimate.get("project") or {},
        "tier": estimate.get("tier") or {},
        "total_range": {"low": totals.get("low"), "high": totals.get("high")},
        "by_category": totals.get("by_category") or {},
        "budget_comparison": {
            "user_budget": comparison.get("user_budget"),
            "status": comparison.get("status"),
            "overrun_items": comparison.get("overrun_items") or [],
        },
        "rooms": [
            {"name": r.get("name"), "area_m2": r.get("area_m2"),
             "subtotal_range": {"low": r.get("subtotal_low"), "high": r.get("subtotal_high")},
             "top_items": sorted(
                 ({"item": i["item"], "category": i["category"], "subtotal_high": i["subtotal_high"]}
                  for i in r.get("items") or []),
                 key=lambda x: -x["subtotal_high"])[:3]}
            for r in estimate.get("rooms") or []
        ],
        "style": (needs_profile or {}).get("style_preferences") or {},
    }
    result = client.chat_json(
        _ENRICH_SYSTEM_PROMPT,
        json.dumps(payload, ensure_ascii=False),
        temperature=0.4,
        max_tokens=2000,
    )
    if not isinstance(result, dict):
        return
    advice = {}
    allocation = str(result.get("allocation_advice") or "").strip()
    if allocation:
        advice["allocation_advice"] = allocation
    tips = [str(t).strip() for t in result.get("saving_tips") or [] if str(t).strip()]
    if tips:
        advice["saving_tips"] = tips[:6]
    if advice:
        estimate["ai_advice"] = advice
    valid_names = {r.get("name") for r in estimate.get("rooms") or []}
    for note in result.get("room_notes") or []:
        if not isinstance(note, dict):
            continue
        name = note.get("name")
        text = str(note.get("note") or "").strip()
        if name in valid_names and text:
            for room in estimate["rooms"]:
                if room["name"] == name:
                    room["note"] = text
    for item in result.get("extra_assumptions") or []:
        text = _assumption(str(item).strip())
        if text and text not in estimate["assumptions"]:
            estimate["assumptions"].append(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blocked_insufficient(reason):
    return {
        "status": "blocked_insufficient_facts",
        "module": "budget_estimate",
        "reasons": [reason],
    }


def _assumption(text):
    text = (text or "").strip()
    if not text:
        return ""
    if not text.startswith("假设："):
        text = "假设：" + text.lstrip("假设:")
    return text


def _money(value):
    return round(_num(value), 2)


def _num(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("㎡", "").replace("m2", "").strip())
    except ValueError:
        return 0
