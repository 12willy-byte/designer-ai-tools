"""Offline validation for M0 Space Cognition and M1 Needs Cognition."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)


def _sample_conditions(path):
    data = {
        "project": {
            "name": "M0M1样例住宅",
            "house_type": "三居室住宅",
            "area_m2": 98,
            "design_type": "整屋自动化方案",
        },
        "family": {
            "residents": "3人",
            "composition": "夫妻二人和一名儿童",
            "children_ages": "6岁",
            "work_from_home": "偶尔",
            "cooking_frequency": "每天，高频中餐",
            "storage_need": "较高",
        },
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
        "special_requirements": {
            "承重墙": "不可拆改，需人工确认原始结构图",
            "烟道": "厨房烟道位置不可移动",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _sample_semantic_scan(path):
    data = {
        "source_type": "roomplan_like_semantic_scan",
        "confidence": 0.72,
        "rooms": [
            {
                "name": "客厅",
                "area_m2": 28.6,
                "width_mm": 5200,
                "length_mm": 5500,
                "ceiling_height_mm": 2680,
                "orientation": "南",
                "adjacent_to": ["阳台", "餐厅", "走廊"],
            },
            {
                "name": "厨房",
                "area_m2": 7.2,
                "width_mm": 3000,
                "length_mm": 2400,
                "ceiling_height_mm": 2600,
                "orientation": "北",
                "adjacent_to": ["餐厅"],
            },
        ],
        "openings": [
            {"type": "door", "room": "客厅", "width_mm": 860, "connects_to": "走廊", "confidence": 0.7},
            {"type": "window", "room": "客厅", "width_mm": 2400, "orientation": "南", "confidence": 0.72},
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    from core.scan_importer import summarize_scan_file
    from core.space_profile import build_space_cognition_package
    from core.needs_profile import build_needs_cognition_package

    with tempfile.TemporaryDirectory() as tmp:
        conditions_path = os.path.join(tmp, "design_conditions.json")
        scan_path = os.path.join(tmp, "roomplan_scan.json")
        out_dir = os.path.join(tmp, "cognition_output")
        _sample_conditions(conditions_path)
        _sample_semantic_scan(scan_path)

        with open(conditions_path, "r", encoding="utf-8") as f:
            conditions = json.load(f)
        scan_summary = summarize_scan_file(scan_path)
        space_package = build_space_cognition_package(
            conditions,
            out_dir,
            scan_summary=scan_summary,
            source_files={"scan": scan_path},
        )
        needs_package = build_needs_cognition_package(
            conditions,
            out_dir,
            space_profile=space_package["profile"],
        )

        required = [
            space_package["space_profile"],
            space_package["scan_summary"],
            space_package["space_observations"],
            space_package["questions_to_confirm"],
            needs_package["needs_profile"],
            needs_package["needs_observations"],
            needs_package["needs_questions_to_confirm"],
        ]
        missing = [path for path in required if not path or not os.path.exists(path)]
        if missing:
            raise SystemExit("Missing cognition outputs: " + ", ".join(missing))

        if "concept_package" not in space_package["profile"]["readiness"]["ready_for"]:
            raise SystemExit("M0 is not ready for concept package")
        if "concept_package" not in needs_package["profile"]["readiness"]["ready_for"]:
            raise SystemExit("M1 is not ready for concept package")

        print(json.dumps({
            "ok": True,
            "scan_confidence": scan_summary["confidence"],
            "space_ready_for": space_package["profile"]["readiness"]["ready_for"],
            "needs_ready_for": needs_package["profile"]["readiness"]["ready_for"],
            "space_questions": len(space_package["profile"]["questions_to_confirm"]),
            "needs_questions": len(needs_package["profile"]["questions_to_confirm"]),
            "output_dir": out_dir,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
