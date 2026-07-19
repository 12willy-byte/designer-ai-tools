"""MVP concept package pipeline.

Input: design_conditions.json
Output: concept_output assets and a PPTX concept deck.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from modules.m2_concept_design.step1_design_brief import generate_design_brief
from modules.m2_concept_design.step2_color_palette import generate_color_palette
from modules.m2_concept_design.step3_material_board import generate_material_board
from modules.m2_concept_design.step4_mood_board import generate_mood_board
from modules.m2_concept_design.step5_layout_sketch import generate_layout
from modules.m2_concept_design.step7_build_pptx import build_pptx
from core.space_profile import build_space_cognition_package
from core.needs_profile import build_needs_cognition_package
from core.automation_gate import build_automation_gate_package, explain_blocked_module


def run_mvp_concept_package(
    conditions_json_path,
    output_pptx_path=None,
    scan_summary=None,
    cad_plan=None,
    cad_dxf_path=None,
):
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    os.makedirs(out_dir, exist_ok=True)

    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    if cad_dxf_path and cad_plan is None:
        from core.cad_reader import read_dxf_with_rooms
        cad_plan = read_dxf_with_rooms(cad_dxf_path)

    source_files = {}
    if cad_dxf_path:
        source_files["cad"] = cad_dxf_path
    space_package = build_space_cognition_package(
        conditions,
        out_dir,
        cad_plan=cad_plan,
        scan_summary=scan_summary,
        source_files=source_files,
    )
    needs_package = build_needs_cognition_package(
        conditions,
        out_dir,
        space_profile=space_package["profile"],
    )
    gate_package = build_automation_gate_package(
        space_package["profile"],
        needs_package["profile"],
        out_dir,
    )
    gate = gate_package["gate"]
    if "concept_package" not in gate["allowed"]:
        reasons = explain_blocked_module(gate, "concept_package")
        raise ValueError("资料不足，无法生成概念提案包：" + "；".join(reasons))

    brief = generate_design_brief(conditions_json_path)
    with open(os.path.join(out_dir, "设计定位.txt"), "w", encoding="utf-8") as f:
        f.write(brief.get("design_brief") or brief.get("raw_text") or "")
    with open(os.path.join(out_dir, "设计定位.json"), "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)

    palette = generate_color_palette(conditions_json_path)
    materials = generate_material_board(conditions_json_path)
    mood_board_path = generate_mood_board(conditions_json_path)
    if "layout_draft" in gate["allowed"]:
        layout = generate_layout(conditions_json_path)
    else:
        layout = {
            "status": "blocked_by_automation_gate",
            "module": "layout_draft",
            "reasons": explain_blocked_module(gate, "layout_draft"),
        }
    with open(os.path.join(out_dir, "布局方案.json"), "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)

    if output_pptx_path is None:
        output_pptx_path = os.path.join(out_dir, "概念方案.pptx")
    pptx_path = build_pptx(conditions_json_path, output_pptx_path)

    return {
        "output_dir": out_dir,
        "pptx": pptx_path,
        "brief": os.path.join(out_dir, "设计定位.txt"),
        "palette_image": palette.get("palette_image"),
        "material_image": materials.get("board_image"),
        "mood_board": mood_board_path,
        "layout_json": os.path.join(out_dir, "布局方案.json"),
        "space_profile": space_package["space_profile"],
        "cad_plan": space_package["cad_plan"],
        "scan_summary": space_package["scan_summary"],
        "space_observations": space_package["space_observations"],
        "questions_to_confirm": space_package["questions_to_confirm"],
        "needs_profile": needs_package["needs_profile"],
        "needs_observations": needs_package["needs_observations"],
        "needs_questions_to_confirm": needs_package["needs_questions_to_confirm"],
        "automation_gate": gate_package["automation_gate"],
        "constraint_report": gate_package["constraint_report"],
        "unified_questions_to_confirm": gate_package["unified_questions_to_confirm"],
        "allowed_modules": gate["allowed"],
        "blocked_modules": gate["blocked"],
        "demo_mode": bool(palette.get("demo") or materials.get("demo") or layout.get("demo")),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m modules.m2_concept_design.mvp_pipeline <design_conditions.json> [output.pptx] [cad.dxf]")
        raise SystemExit(2)
    result = run_mvp_concept_package(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
        cad_dxf_path=sys.argv[3] if len(sys.argv) > 3 else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
