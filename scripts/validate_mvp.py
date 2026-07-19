"""Offline MVP validation for the concept-package chain."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)


def _sample_conditions(path):
    data = {
        "project": {"name": "MVP样例住宅", "house_type": "三居室", "area_m2": 98},
        "family": {"residents": "3人", "work_from_home": "偶尔", "storage_need": "较高"},
        "style": {
            "primary_style": "现代简约",
            "color_tone": "暖白、木色、低饱和蓝灰",
            "keywords": "通透 温润 收纳",
            "floor_material": "木地板",
            "wall_material": "乳胶漆",
        },
        "rooms": [
            {"name": "客厅", "width_mm": 5200, "height_mm": 4200, "requirements": {"功能": "会客、观影、亲子活动"}},
            {"name": "主卧", "width_mm": 3900, "height_mm": 3600, "requirements": {"功能": "睡眠、衣物收纳"}},
            {"name": "厨房", "width_mm": 3000, "height_mm": 2400, "requirements": {"功能": "高频中餐"}},
        ],
        "budget": {"total_budget": 350000},
        "special_requirements": {"环保": "低VOC"},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    os.environ["AI_DEMO_MODE"] = "1"
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    with tempfile.TemporaryDirectory() as tmp:
        conditions_path = os.path.join(tmp, "design_conditions.json")
        _sample_conditions(conditions_path)
        result = run_mvp_concept_package(conditions_path)
        required = [
            result["space_profile"],
            result["space_observations"],
            result["questions_to_confirm"],
            result["needs_profile"],
            result["needs_observations"],
            result["needs_questions_to_confirm"],
            result["automation_gate"],
            result["constraint_report"],
            result["unified_questions_to_confirm"],
            result["pptx"],
            result["brief"],
            result["palette_image"],
            result["material_image"],
            result["mood_board"],
            result["layout_json"],
        ]
        missing = [p for p in required if not p or not os.path.exists(p)]
        if missing:
            raise SystemExit("Missing MVP outputs: " + ", ".join(missing))
        with open(result["layout_json"], "r", encoding="utf-8") as f:
            layout = json.load(f)
        if layout.get("status") != "blocked_by_automation_gate":
            raise SystemExit("MVP sample should block layout until structure/MEP/door facts are known")
        print(json.dumps({
            "ok": True,
            "output_dir": result["output_dir"],
            "pptx_size": os.path.getsize(result["pptx"]),
            "allowed_modules": result["allowed_modules"],
            "blocked_modules": [item["module"] for item in result["blocked_modules"]],
            "demo_mode": result["demo_mode"],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
