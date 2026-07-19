"""Offline validation for the Space Profile foundation module."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)


def _sample_conditions(path):
    data = {
        "project": {
            "name": "自动化样例住宅",
            "house_type": "三居室住宅",
            "area_m2": 98,
            "design_type": "整屋概念方案",
        },
        "rooms": [
            {
                "name": "客厅",
                "width_mm": 5200,
                "height_mm": 4200,
                "orientation": "南",
                "adjacent_to": ["阳台", "餐厅"],
                "requirements": {"功能": "会客、观影、亲子活动"},
            },
            {
                "name": "主卧",
                "width_mm": 3900,
                "height_mm": 3600,
                "orientation": "南",
                "requirements": {"功能": "睡眠、衣物收纳"},
            },
            {
                "name": "厨房",
                "width_mm": 3000,
                "height_mm": 2400,
                "orientation": "北",
                "requirements": {"功能": "高频中餐"},
            },
        ],
        "budget": {"total_budget": 350000},
        "special_requirements": {
            "承重墙": "不可拆改，需人工确认原始结构图",
            "烟道": "厨房烟道位置不可移动",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    from core.space_profile import build_space_profile_from_file, save_space_profile

    with tempfile.TemporaryDirectory() as tmp:
        conditions_path = os.path.join(tmp, "design_conditions.json")
        output_path = os.path.join(tmp, "space_profile.json")
        _sample_conditions(conditions_path)
        profile = build_space_profile_from_file(conditions_path)
        save_space_profile(profile, output_path)

        readiness = profile["readiness"]
        if "concept_package" not in readiness["ready_for"]:
            raise SystemExit("Space Profile is not ready for concept package")
        if not os.path.exists(output_path):
            raise SystemExit("space_profile.json was not created")
        if not profile.get("observations"):
            raise SystemExit("space observations were not created")
        if not profile.get("questions_to_confirm"):
            raise SystemExit("confirmation questions were not created")

        print(json.dumps({
            "ok": True,
            "schema_version": profile["schema_version"],
            "ready_for": readiness["ready_for"],
            "score": readiness["score"],
            "rooms": len(profile["geometry"]["rooms"]),
            "questions": len(profile["questions_to_confirm"]),
            "output_path": output_path,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
