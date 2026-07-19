"""Automation gate between cognition modules and design generation.

M2 does not generate a design. It decides which downstream outputs are safe
enough to attempt from the current space profile and owner-needs profile.
"""
import json
import os


SCHEMA_VERSION = "automation_gate.v1"
CONSTRAINT_REPORT_VERSION = "constraint_report.v1"

MODULE_LABELS = {
    "concept_package": "概念提案包",
    "layout_draft": "布局草案",
    "budget_estimate": "预算估算",
    "material_palette": "材料/色彩建议",
    "construction_docs": "施工级图纸/文档",
}


def build_automation_gate(space_profile, needs_profile, constraint_report=None, unified_questions=None):
    """Return the M2 gate decision for downstream automation."""
    space_profile = space_profile or {}
    needs_profile = needs_profile or {}
    constraint_report = constraint_report or build_constraint_report(space_profile, needs_profile)
    unified_questions = unified_questions or build_unified_questions(space_profile, needs_profile)

    allowed = []
    blocked = []
    warnings = _collect_warnings(space_profile, needs_profile, constraint_report)

    _decide_concept_package(space_profile, needs_profile, allowed, blocked)
    _decide_layout_draft(space_profile, needs_profile, constraint_report, allowed, blocked)
    _decide_budget_estimate(space_profile, needs_profile, allowed, blocked)
    _decide_material_palette(needs_profile, allowed, blocked, warnings)
    _block_construction_docs(blocked, constraint_report)

    required_confirmations = [q for q in unified_questions if q.get("required")]
    scores = {
        "space": _readiness_score(space_profile),
        "needs": _readiness_score(needs_profile),
    }
    scores["gate"] = _gate_score(scores["space"], scores["needs"], blocked, required_confirmations, warnings)

    return {
        "schema_version": SCHEMA_VERSION,
        "allowed": allowed,
        "blocked": blocked,
        "warnings": _dedupe_strings(warnings),
        "required_confirmations": required_confirmations,
        "scores": scores,
        "constraint_summary": {
            "critical_missing": constraint_report.get("critical_missing", []),
            "layout_missing": constraint_report.get("layout_missing", []),
        },
    }


def build_constraint_report(space_profile, needs_profile=None):
    """Summarize hard constraints and missing facts before design generation."""
    space_profile = space_profile or {}
    needs_profile = needs_profile or {}
    geometry = space_profile.get("geometry") or {}
    constraints = space_profile.get("constraints") or {}
    structural = constraints.get("structural") or []
    mep = constraints.get("mep") or []
    rooms = geometry.get("rooms") or []
    doors = geometry.get("doors") or []
    windows = geometry.get("windows") or []

    critical_missing = []
    layout_missing = []
    if not rooms:
        critical_missing.append("缺少房间/空间列表")
    if not structural:
        critical_missing.append("缺少承重墙、梁、柱、不可拆改边界")
        layout_missing.append("缺少结构边界，不能自动判断拆改和家具/柜体避让")
    if not mep:
        critical_missing.append("缺少管井、烟道、上下水、燃气或强弱电位置")
        layout_missing.append("缺少机电/湿区约束，不能自动判断厨房、卫生间和设备位置")
    if not doors:
        layout_missing.append("缺少门洞位置，不能可靠判断入口和动线")
    if not windows:
        layout_missing.append("缺少窗户/采光面位置，色彩、采光和视觉焦点需要复核")

    budget = _budget(needs_profile) or constraints.get("budget") or {}
    if not budget.get("total_budget"):
        critical_missing.append("缺少总预算或预算区间")

    return {
        "schema_version": CONSTRAINT_REPORT_VERSION,
        "known_constraints": {
            "structural": structural,
            "mep": mep,
            "budget": budget,
            "special_unknowns": constraints.get("unknowns") or [],
        },
        "space_facts": {
            "room_count": len(rooms),
            "geometry_source": geometry.get("source_type", ""),
            "geometry_confidence": geometry.get("confidence", 0),
            "has_doors": bool(doors),
            "has_windows": bool(windows),
            "bounds_mm": geometry.get("bounds_mm"),
        },
        "critical_missing": _dedupe_strings(critical_missing),
        "layout_missing": _dedupe_strings(layout_missing),
        "automation_boundaries": [
            "概念提案可以基于低风险空间事实和需求画像生成。",
            "布局草案必须建立在门洞、结构边界和机电/湿区约束已知的前提上。",
            "施工级图纸不属于当前 MVP 自动生成范围，必须由设计师基于原始图纸复核。",
        ],
    }


def build_unified_questions(space_profile, needs_profile):
    """Merge M0 and M1 confirmation questions into one deduplicated list."""
    questions = []
    seen = set()
    for source, profile in (("space", space_profile or {}), ("needs", needs_profile or {})):
        for item in profile.get("questions_to_confirm") or []:
            question = (item.get("question") or "").strip()
            if not question or question in seen:
                continue
            seen.add(question)
            merged = dict(item)
            merged["source"] = source
            questions.append(merged)
    return questions


def build_automation_gate_package(space_profile, needs_profile, output_dir):
    """Write M2 gate artifacts and return their paths plus in-memory data."""
    os.makedirs(output_dir, exist_ok=True)
    constraint_report = build_constraint_report(space_profile, needs_profile)
    unified_questions = build_unified_questions(space_profile, needs_profile)
    gate = build_automation_gate(
        space_profile,
        needs_profile,
        constraint_report=constraint_report,
        unified_questions=unified_questions,
    )

    gate_path = os.path.join(output_dir, "automation_gate.json")
    report_path = os.path.join(output_dir, "constraint_report.json")
    questions_path = os.path.join(output_dir, "unified_questions_to_confirm.json")
    _write_json(gate_path, gate)
    _write_json(report_path, constraint_report)
    _write_json(questions_path, unified_questions)

    return {
        "automation_gate": gate_path,
        "constraint_report": report_path,
        "unified_questions_to_confirm": questions_path,
        "gate": gate,
        "report": constraint_report,
        "questions": unified_questions,
    }


def explain_blocked_module(gate, module):
    """Return human-readable reasons for a blocked module."""
    for item in (gate or {}).get("blocked") or []:
        if item.get("module") == module:
            return item.get("reasons") or []
    return []


def _decide_concept_package(space_profile, needs_profile, allowed, blocked):
    reasons = []
    if not _ready_for(space_profile, "concept_package"):
        reasons.extend(_readiness_reasons(space_profile, "空间对象不足以生成概念提案"))
    if not _ready_for(needs_profile, "concept_package"):
        reasons.extend(_readiness_reasons(needs_profile, "业主需求不足以生成概念提案"))
    _allow_or_block("concept_package", reasons, allowed, blocked)


def _decide_layout_draft(space_profile, needs_profile, constraint_report, allowed, blocked):
    reasons = []
    if not _ready_for(space_profile, "layout_draft"):
        reasons.extend(_readiness_reasons(space_profile, "空间对象不足以生成布局草案"))
    if not _ready_for(needs_profile, "concept_package"):
        reasons.extend(_readiness_reasons(needs_profile, "业主需求不足以支撑布局取舍"))
    reasons.extend(constraint_report.get("layout_missing") or [])
    _allow_or_block("layout_draft", reasons, allowed, blocked)


def _decide_budget_estimate(space_profile, needs_profile, allowed, blocked):
    reasons = []
    if not _ready_for(space_profile, "budget_estimate"):
        reasons.extend(_readiness_reasons(space_profile, "空间面积不足以做预算估算"))
    if not _ready_for(needs_profile, "budget_estimate"):
        reasons.extend(_readiness_reasons(needs_profile, "预算信息不足以做预算估算"))
    _allow_or_block("budget_estimate", reasons, allowed, blocked)


def _decide_material_palette(needs_profile, allowed, blocked, warnings):
    reasons = []
    if not _ready_for(needs_profile, "concept_package"):
        reasons.extend(_readiness_reasons(needs_profile, "业主需求不足以生成材料/色彩建议"))
    if not _has_style(needs_profile):
        reasons.append("缺少风格偏好或风格关键词")
    if not (_budget(needs_profile) or {}).get("total_budget"):
        warnings.append("缺少总预算，材料/色彩建议只能按风格方向给出，不能稳定匹配档次。")
    _allow_or_block("material_palette", reasons, allowed, blocked)


def _block_construction_docs(blocked, constraint_report):
    reasons = [
        "当前 MVP 不生成施工级图纸/文档。",
        "缺少原始结构图、完整尺寸复核、机电点位和施工标准校核。",
    ]
    for missing in constraint_report.get("critical_missing") or []:
        if missing not in reasons:
            reasons.append(missing)
    blocked.append({
        "module": "construction_docs",
        "label": MODULE_LABELS["construction_docs"],
        "reasons": _dedupe_strings(reasons),
    })


def _allow_or_block(module, reasons, allowed, blocked):
    reasons = _dedupe_strings(reasons)
    if reasons:
        blocked.append({
            "module": module,
            "label": MODULE_LABELS.get(module, module),
            "reasons": reasons,
        })
    else:
        allowed.append(module)


def _ready_for(profile, module):
    readiness = (profile or {}).get("readiness") or {}
    return module in (readiness.get("ready_for") or [])


def _readiness_score(profile):
    readiness = (profile or {}).get("readiness") or {}
    return int(readiness.get("score") or 0)


def _readiness_reasons(profile, fallback):
    readiness = (profile or {}).get("readiness") or {}
    reasons = []
    reasons.extend(readiness.get("blocking_issues") or [])
    if not reasons:
        reasons.extend(readiness.get("warnings") or [])
    if not reasons:
        reasons.append(fallback)
    return reasons


def _collect_warnings(space_profile, needs_profile, constraint_report):
    warnings = []
    for profile in (space_profile or {}, needs_profile or {}):
        readiness = profile.get("readiness") or {}
        warnings.extend(readiness.get("warnings") or [])
        warnings.extend(readiness.get("unknowns") or [])
    if (constraint_report.get("space_facts") or {}).get("geometry_confidence", 0) < 0.6:
        warnings.append("空间几何置信度低于 0.6，后续自动化结果必须人工复核。")
    return warnings


def _gate_score(space_score, needs_score, blocked, required_confirmations, warnings):
    score = (space_score + needs_score) / 2
    score -= max(0, len(blocked) - 1) * 8
    score -= len(required_confirmations) * 4
    score -= len(warnings) * 2
    return int(max(0, min(100, round(score))))


def _has_style(needs_profile):
    style = (needs_profile or {}).get("style_preferences") or {}
    return bool(style.get("primary_style") or style.get("keywords"))


def _budget(needs_profile):
    return (needs_profile or {}).get("budget") or {}


def _dedupe_strings(items):
    result = []
    seen = set()
    for item in items or []:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
