"""Offline validation for M2 Automation Gate."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)


def _complete_conditions(path):
    data = {
        "project": {
            "name": "M2样例住宅",
            "house_type": "三居室住宅",
            "area_m2": 98,
            "design_type": "整屋自动化方案",
        },
        "family": {
            "residents": "3人",
            "composition": "夫妻二人和一名儿童",
            "work_from_home": "偶尔",
            "cooking_frequency": "每天，高频中餐",
            "storage_need": "较高",
        },
        "style": {
            "primary_style": "现代简约",
            "color_tone": "暖白、木色、低饱和蓝灰",
            "keywords": "通透 温润 收纳",
        },
        "rooms": [
            {"name": "客厅", "width_mm": 5200, "height_mm": 4200},
            {"name": "主卧", "width_mm": 3900, "height_mm": 3600},
            {"name": "厨房", "width_mm": 3000, "height_mm": 2400},
        ],
        "budget": {"total_budget": 350000},
        "special_requirements": {
            "承重墙": "不可拆改，需人工确认原始结构图",
            "烟道": "厨房烟道位置不可移动",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _semantic_scan(path):
    data = {
        "source_type": "roomplan_like_semantic_scan",
        "confidence": 0.72,
        "rooms": [
            {
                "name": "客厅",
                "area_m2": 28.6,
                "width_mm": 5200,
                "length_mm": 5500,
                "orientation": "南",
                "adjacent_to": ["阳台", "餐厅", "走廊"],
            }
        ],
        "openings": [
            {"type": "door", "room": "客厅", "width_mm": 860, "connects_to": "走廊", "confidence": 0.7},
            {"type": "window", "room": "客厅", "width_mm": 2400, "orientation": "南", "confidence": 0.72},
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _incomplete_conditions():
    return {
        "project": {"name": "缺资料样例", "house_type": "两居室", "area_m2": 72},
        "family": {"residents": "2人", "storage_need": "较高"},
        "style": {"primary_style": "现代简约", "keywords": "耐看 收纳"},
        "rooms": [
            {"name": "客厅", "width_mm": 4200, "height_mm": 3900},
            {"name": "卧室", "width_mm": 3600, "height_mm": 3300},
        ],
        "budget": {"total_budget": 220000},
    }


def main():
    from core.scan_importer import summarize_scan_file
    from core.space_profile import build_space_cognition_package, build_space_profile
    from core.needs_profile import build_needs_cognition_package, build_needs_profile
    from core.automation_gate import build_automation_gate_package, build_automation_gate

    with tempfile.TemporaryDirectory() as tmp:
        conditions_path = os.path.join(tmp, "design_conditions.json")
        scan_path = os.path.join(tmp, "roomplan_scan.json")
        out_dir = os.path.join(tmp, "gate_output")
        _complete_conditions(conditions_path)
        _semantic_scan(scan_path)

        with open(conditions_path, "r", encoding="utf-8") as f:
            conditions = json.load(f)
        scan_summary = summarize_scan_file(scan_path)
        space_package = build_space_cognition_package(conditions, out_dir, scan_summary=scan_summary)
        needs_package = build_needs_cognition_package(conditions, out_dir, space_profile=space_package["profile"])
        gate_package = build_automation_gate_package(space_package["profile"], needs_package["profile"], out_dir)

        required = [
            gate_package["automation_gate"],
            gate_package["constraint_report"],
            gate_package["unified_questions_to_confirm"],
        ]
        missing = [path for path in required if not path or not os.path.exists(path)]
        if missing:
            raise SystemExit("Missing M2 outputs: " + ", ".join(missing))

        gate = gate_package["gate"]
        for module in ("concept_package", "layout_draft", "budget_estimate", "material_palette"):
            if module not in gate["allowed"]:
                raise SystemExit(f"M2 should allow {module} for complete sample")

        blocked_modules = [item["module"] for item in gate["blocked"]]
        if "construction_docs" not in blocked_modules:
            raise SystemExit("M2 must block construction_docs in MVP")

        incomplete = _incomplete_conditions()
        incomplete_space = build_space_profile(incomplete)
        incomplete_needs = build_needs_profile(incomplete, space_profile=incomplete_space)
        incomplete_gate = build_automation_gate(incomplete_space, incomplete_needs)
        if "concept_package" not in incomplete_gate["allowed"]:
            raise SystemExit("Incomplete sample should still allow concept_package")
        if "layout_draft" in incomplete_gate["allowed"]:
            raise SystemExit("Incomplete sample should block layout_draft")

        print(json.dumps({
            "ok": True,
            "allowed": gate["allowed"],
            "blocked": blocked_modules,
            "incomplete_blocked": [item["module"] for item in incomplete_gate["blocked"]],
            "score": gate["scores"]["gate"],
            "output_dir": out_dir,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
