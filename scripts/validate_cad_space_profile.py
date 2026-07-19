"""Offline validation for CAD/DXF as an M0 Space Profile input."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)


def _sample_conditions(path):
    data = {
        "project": {
            "name": "CAD样例住宅",
            "house_type": "一居室住宅",
            "area_m2": 24,
            "design_type": "整屋自动化方案",
        },
        "family": {
            "residents": "1人",
            "composition": "独居",
            "work_from_home": "经常",
            "cooking_frequency": "每周数次",
            "storage_need": "中等",
        },
        "style": {
            "primary_style": "现代简约",
            "keywords": "清爽 高效 收纳",
            "color_tone": "白色、浅木色、灰色",
        },
        "budget": {"total_budget": 120000},
        "special_requirements": {
            "承重墙": "外墙及结构墙不可拆改，需保留",
            "上下水": "厨房与卫生间湿区位置不可移动",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _sample_dxf(path):
    import ezdxf

    doc = ezdxf.new("R2010")
    for layer in ("墙体", "门", "窗", "房间标注"):
        if layer not in [item.dxf.name for item in doc.layers]:
            doc.layers.add(layer)

    msp = doc.modelspace()
    # 6000 x 4000 mm rectangular room.
    msp.add_lwpolyline(
        [(0, 0), (6000, 0), (6000, 4000), (0, 4000)],
        close=True,
        dxfattribs={"layer": "墙体"},
    )
    msp.add_line((2600, 0), (3400, 0), dxfattribs={"layer": "门"})
    msp.add_line((1800, 4000), (4200, 4000), dxfattribs={"layer": "窗"})
    msp.add_text("客厅", height=250, dxfattribs={"layer": "房间标注"}).set_placement((3000, 2000))
    doc.saveas(path)


def main():
    from core.cad_reader import read_dxf_with_rooms
    from core.space_profile import build_space_cognition_package
    from core.needs_profile import build_needs_cognition_package
    from core.automation_gate import build_automation_gate_package
    from core.ai_client import reset_client
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    with tempfile.TemporaryDirectory() as tmp:
        conditions_path = os.path.join(tmp, "design_conditions.json")
        cad_path = os.path.join(tmp, "sample_floor_plan.dxf")
        out_dir = os.path.join(tmp, "cad_output")
        _sample_conditions(conditions_path)
        _sample_dxf(cad_path)

        with open(conditions_path, "r", encoding="utf-8") as f:
            conditions = json.load(f)
        cad_plan = read_dxf_with_rooms(cad_path)
        if not cad_plan.get("detected_rooms"):
            raise SystemExit("CAD reader did not detect any room loops")
        if not cad_plan.get("doors") or not cad_plan.get("windows"):
            raise SystemExit("CAD reader did not detect door/window segments")

        space_package = build_space_cognition_package(
            conditions,
            out_dir,
            cad_plan=cad_plan,
            source_files={"cad": cad_path},
        )
        needs_package = build_needs_cognition_package(
            conditions,
            out_dir,
            space_profile=space_package["profile"],
        )
        gate_package = build_automation_gate_package(space_package["profile"], needs_package["profile"], out_dir)

        profile = space_package["profile"]
        gate = gate_package["gate"]
        required = [
            space_package["space_profile"],
            space_package["cad_plan"],
            space_package["space_observations"],
            space_package["questions_to_confirm"],
            gate_package["automation_gate"],
            gate_package["constraint_report"],
        ]
        missing = [path for path in required if not path or not os.path.exists(path)]
        if missing:
            raise SystemExit("Missing CAD cognition outputs: " + ", ".join(missing))
        if profile["geometry"]["source_type"] != "cad":
            raise SystemExit("Space Profile did not mark CAD as geometry source")
        if "layout_draft" not in profile["readiness"]["ready_for"]:
            raise SystemExit("Space Profile should be ready for layout_draft from CAD sample")
        if "layout_draft" not in gate["allowed"]:
            raise SystemExit("M2 should allow layout_draft when CAD + structure + MEP constraints are present")

        os.environ["AI_DEMO_MODE"] = "1"
        reset_client()
        pipeline_result = run_mvp_concept_package(conditions_path, cad_dxf_path=cad_path)
        if not pipeline_result.get("cad_plan") or not os.path.exists(pipeline_result["cad_plan"]):
            raise SystemExit("MVP pipeline did not write cad_plan.json")
        if "layout_draft" not in pipeline_result.get("allowed_modules", []):
            raise SystemExit("MVP pipeline did not allow layout_draft with CAD input")
        with open(pipeline_result["layout_json"], "r", encoding="utf-8") as f:
            layout_json = json.load(f)
        if layout_json.get("status") == "blocked_by_automation_gate":
            raise SystemExit("MVP pipeline unexpectedly blocked layout_draft with CAD input")

        print(json.dumps({
            "ok": True,
            "cad_rooms": len(cad_plan["detected_rooms"]),
            "doors": len(cad_plan["doors"]),
            "windows": len(cad_plan["windows"]),
            "space_ready_for": profile["readiness"]["ready_for"],
            "allowed": gate["allowed"],
            "blocked": [item["module"] for item in gate["blocked"]],
            "pipeline_pptx_size": os.path.getsize(pipeline_result["pptx"]),
            "output_dir": out_dir,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
