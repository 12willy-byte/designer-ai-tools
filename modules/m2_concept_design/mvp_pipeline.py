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
from modules.m2_concept_design.step5_layout_sketch import generate_layout_draft
from modules.m2_concept_design.step7_build_pptx import build_pptx
from core.space_profile import build_space_cognition_package
from core.needs_profile import build_needs_cognition_package
from core.automation_gate import build_automation_gate_package, explain_blocked_module
from core.budget_estimate import build_budget_estimate_package
from core.delivery_package import build_delivery_package


def run_mvp_concept_package(
    conditions_json_path,
    output_pptx_path=None,
    scan_summary=None,
    cad_plan=None,
    cad_dxf_path=None,
    pdf_path=None,
    pdf_scale=None,
    delivery_root=None,
    delivery_package_name=None,
):
    base_dir = os.path.dirname(os.path.abspath(conditions_json_path))
    out_dir = os.path.join(base_dir, "concept_output")
    os.makedirs(out_dir, exist_ok=True)

    with open(conditions_json_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    if cad_dxf_path and cad_plan is None:
        from core.cad_reader import read_dxf_with_rooms
        cad_plan = read_dxf_with_rooms(cad_dxf_path)
    if pdf_path:
        # 矢量 PDF 与 cad_plan 同构，走同一融合通道；CAD/DXF 优先。
        from core.pdf_plan_reader import read_pdf_plan
        pdf_plan = read_pdf_plan(pdf_path, scale=pdf_scale)
        if not pdf_plan.get("accepted"):
            raise ValueError("PDF 图纸无法作为空间输入：" +
                             "；".join(pdf_plan.get("limitations") or ["未知原因"]))
        if cad_plan is None:
            cad_plan = pdf_plan

    source_files = {}
    if cad_dxf_path:
        source_files["cad"] = cad_dxf_path
    if pdf_path:
        source_files["pdf"] = pdf_path
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
        layout = generate_layout_draft(
            space_package["profile"],
            needs_package["profile"],
            gate=gate,
            output_dir=out_dir,
        )
    else:
        layout = {
            "status": "blocked_by_automation_gate",
            "module": "layout_draft",
            "reasons": explain_blocked_module(gate, "layout_draft"),
        }
    with open(os.path.join(out_dir, "布局方案.json"), "w", encoding="utf-8") as f:
        json.dump(layout, f, ensure_ascii=False, indent=2)

    # M5 预算与材料清单：闸门放行 budget_estimate 时生成。
    # 数字全部由规则引擎计算（工程量来自空间事实、单价来自价格基准表），
    # 真实模式下 AI 只写分配/省钱建议文字，不能改动任何数字。
    if "budget_estimate" in gate["allowed"]:
        budget_package = build_budget_estimate_package(
            space_package["profile"],
            needs_package["profile"],
            material_plan=materials,
            layout_draft=layout if layout.get("status") == "draft" else None,
            gate=gate,
            output_dir=out_dir,
        )
        budget = budget_package["estimate"]
    else:
        budget = {
            "status": "blocked_by_automation_gate",
            "module": "budget_estimate",
            "reasons": explain_blocked_module(gate, "budget_estimate"),
        }
        budget_package = {"budget_estimate": None, "material_list": None, "budget_summary_md": None}
    with open(os.path.join(out_dir, "预算方案.json"), "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in budget.items() if k != "_material_list"},
                  f, ensure_ascii=False, indent=2)

    if output_pptx_path is None:
        output_pptx_path = os.path.join(out_dir, "概念方案.pptx")
    pptx_path = build_pptx(conditions_json_path, output_pptx_path)

    # M6 交付打包：把 M0–M5 分散产物一次性打包成可追溯的交付包。
    # 被闸门拦截的模块不伪造文件，只在 manifest / 交付说明中标注原因。
    delivery = build_delivery_package(
        out_dir,
        gate=gate,
        pptx_path=pptx_path,
        delivery_root=delivery_root,
        project_name=(conditions.get("project") or {}).get("name"),
        package_name=delivery_package_name,
    )

    return {
        "output_dir": out_dir,
        "pptx": pptx_path,
        "brief": os.path.join(out_dir, "设计定位.txt"),
        "palette_image": palette.get("palette_image"),
        "material_image": materials.get("board_image"),
        "mood_board": mood_board_path,
        "layout_json": os.path.join(out_dir, "布局方案.json"),
        "layout_draft_json": (layout.get("artifacts") or {}).get("layout_draft"),
        "layout_draft_summary": (layout.get("artifacts") or {}).get("layout_summary_md"),
        "budget_json": os.path.join(out_dir, "预算方案.json"),
        "budget_estimate_json": budget_package.get("budget_estimate"),
        "material_list_json": budget_package.get("material_list"),
        "budget_summary_md": budget_package.get("budget_summary_md"),
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
        "delivery": delivery,
        "demo_mode": bool(palette.get("demo") or materials.get("demo") or layout.get("demo")),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m modules.m2_concept_design.mvp_pipeline <design_conditions.json> [output.pptx] [cad.dxf] [plan.pdf]")
        raise SystemExit(2)
    result = run_mvp_concept_package(
        sys.argv[1],
        sys.argv[2] if len(sys.argv) > 2 else None,
        cad_dxf_path=sys.argv[3] if len(sys.argv) > 3 else None,
        pdf_path=sys.argv[4] if len(sys.argv) > 4 else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
