"""
Designer AI Automation Tool v3
3D Scene is the single source of truth - all deliverables derive from Scene3D
"""
import sys, os, json, argparse

sys.path.insert(0, os.path.dirname(__file__))

from core.template_generator import generate_template
from core.survey_parser import parse_survey, save_conditions
from core.cad_reader import read_dxf_floor_plan
from core.scene3d import Scene3D

from assistants.floor_plan_generator import generate_floor_plan
from assistants.quantity_takeoff import calculate_from_scene, generate_pricing, calculate_and_price
from assistants.material_checklist import generate_material_checklist
from assistants.furniture_layout import apply_layout, generate_layout_report
from assistants.furniture_layout_ai import apply_ai_layout
from assistants.renderer import export_threejs_html
from assistants.construction_docs import generate_construction_docs, generate_door_window_schedule, generate_room_finish_schedule
from assistants.construction_drawings import generate_all_drawings, generate_furniture_plan_svg
from export.to_gltf import export_scene_to_gltf
from assistants.checklist_generator import (
    generate_acceptance_checklist, generate_construction_schedule,
)
from assistants.spatial_vision import analyze_room_photos, analyze_style_reference, spatial_qa
from assistants.pointcloud_analyzer import analyze_roomplan

from export.to_excel import (
    export_budget_to_excel, export_material_list_to_excel, export_schedule_to_excel,
)
from export.to_pdf import export_checklist_pdf


def _load_scene(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if "walls" in raw and "rooms" in raw:
            return Scene3D.from_json(path)
        elif "surfaces" in raw:
            return Scene3D.from_roomplan(path)
        else:
            raise ValueError("Unknown JSON format: " + path)
    elif ext in (".dxf",):
        return Scene3D.from_cad(path)
    else:
        raise ValueError("Unsupported format: " + ext)


def _load_conditions(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return parse_survey(path)
    elif ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        raise ValueError("Unsupported format: " + ext)

def cmd_template(args):
    path = args.output or "templates/survey_template.xlsx"
    result = generate_template(path)
    print("Template: " + result)

def cmd_parse(args):
    conditions = parse_survey(args.input)
    path = args.output or "templates/design_conditions.json"
    save_conditions(conditions, path)
    print("Conditions saved: " + path)

def cmd_cad(args):
    plan = read_dxf_floor_plan(args.input)
    print("CAD: %d lines, %d texts" % (plan.get("total_lines", 0), len(plan.get("texts", []))))

def cmd_scan(args):
    result = analyze_roomplan(args.input)
    output = args.output or "output/scan_analysis.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Scan saved: " + output)

def cmd_build(args):
    if args.scan:
        scene = Scene3D.from_roomplan(args.scan)
    elif args.cad:
        scene = Scene3D.from_cad(args.cad)
    elif args.scene:
        scene = _load_scene(args.scene)
    else:
        print("Need --scan / --cad / --scene")
        return
    if args.conditions:
        cond = _load_conditions(args.conditions)
        scene.apply_design_conditions(cond)
    if args.layout:
        apply_ai_layout(scene)
    output = args.output or "output/scene.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    scene.save(output)
    print("Scene: %d rooms, %d walls, %.1f m2 -> %s" % (scene.room_count, len(scene.walls), scene.total_floor_area_m2, output))

def cmd_floorplan(args):
    scene = _load_scene(args.scene)
    dxf_path = args.dxf or "output/floor_plan.dxf"
    png_path = args.png or "output/floor_plan.png"
    generate_floor_plan(scene, dxf_path, png_path)
    print("Floor plan: %s + %s" % (dxf_path, png_path))

def cmd_budget(args):
    scene = _load_scene(args.scene)
    q, pricing = calculate_and_price(scene, args.region or "national_avg")
    output = args.output or "output/budget.xlsx"
    export_budget_to_excel(pricing, output)
    total = sum(it["total"] for it in pricing)
    print("Budget: %,.0f CNY -> %s" % (total, output))

def cmd_materials(args):
    scene = _load_scene(args.scene)
    mats = generate_material_checklist(scene, scene.style)
    output = args.output or "output/materials.xlsx"
    export_material_list_to_excel(mats, output)
    print("Materials: %d categories -> %s" % (len(mats["summary"]), output))

def cmd_layout(args):
    scene = _load_scene(args.scene)
    apply_ai_layout(scene)
    output = args.output or "output/scene.json"
    scene.save(output)
    print("Layout applied: %d furniture -> %s" % (len(scene.furniture) if hasattr(scene, "furniture") else 0, output))

def cmd_render(args):
    scene = _load_scene(args.scene)
    output = args.output or "output/3d_preview.html"
    export_threejs_html(scene, output)
    print("3D preview: " + output)

def cmd_gltf(args):
    scene = _load_scene(args.scene)
    output = args.output or "output/scene.glb"
    export_scene_to_gltf(scene, output)
    print("GLB: " + output)

def cmd_docs(args):
    scene = _load_scene(args.scene)
    docs = generate_construction_docs(scene)
    dw = generate_door_window_schedule(scene)
    rs = generate_room_finish_schedule(scene)
    output = args.output or "output/construction_docs.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump({"docs": docs, "door_window": dw, "room_finish": rs}, f, ensure_ascii=False, indent=2)
    print("Docs: " + output)

def cmd_drawings(args):
    scene = _load_scene(args.scene)
    outdir = args.output or "output/drawings"
    generate_all_drawings(scene, outdir)
    print("Drawings: " + outdir)

def cmd_schedule(args):
    scene = _load_scene(args.scene) if args.scene else None
    schedule = generate_construction_schedule(scene)
    output = args.output or "output/schedule.xlsx"
    export_schedule_to_excel(schedule, output)
    print("Schedule: " + output)

def cmd_checklist(args):
    scene = _load_scene(args.scene) if args.scene else None
    checklist = generate_acceptance_checklist(scene)
    output = args.output or "output/checklist.pdf"
    export_checklist_pdf(checklist, output)
    print("Checklist: " + output)

def cmd_vision(args):
    if args.mode == "room":
        result = analyze_room_photos(args.images, args.provider)
    elif args.mode == "style":
        result = analyze_style_reference(args.images, args.provider)
    elif args.mode == "qa":
        result = spatial_qa(args.images, args.question, args.provider)
    output = args.output or "output/vision_analysis.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Vision: " + output)

def cmd_cloudrender(args):
    from core.cloud_renderer import render_scene
    scene = _load_scene(args.scene)
    task = render_scene(scene, config=args.config or "interior_fast", output_path=args.output)
    print("Render: %s -> %s" % (task.status, task.output_path))

def cmd_ailayout(args):
    scene = _load_scene(args.scene)
    placements = apply_ai_layout(scene)
    output = args.output or "output/scene.json"
    scene.save(output)
    print("AI Layout: %d pieces -> %s" % (len(placements), output))

def cmd_validate(args):
    from core.validation_engine import validate_scene
    scene = _load_scene(args.scene)
    report = validate_scene(scene)
    print("Score: %.0f/100 | Errors: %d | Warnings: %d" % (report.score, len(report.errors), len(report.warnings)))

def cmd_critique(args):
    from assistants.design_critique import critique_design
    result = critique_design(args.scene)
    print(json.dumps(result, ensure_ascii=False, indent=2))

def cmd_estimate(args):
    from core.pricing_engine import estimate_total_cost
    scene = _load_scene(args.scene) if args.scene else None
    result = estimate_total_cost(scene, args.region or "national_avg")
    total = result["summary"]["grand_total"]
    print("Estimated: %,.0f CNY (%.0f CNY/m2)" % (total, result["summary"]["per_sqm"]))

def cmd_photo2scene(args):
    from assistants.image2scene import analyze_with_vlm, generate_scene_from_photos
    vlm = analyze_with_vlm(args.images, args.provider) if not args.no_vlm else None
    scene = generate_scene_from_photos(args.images, vlm_analysis=vlm, output_path=args.output)
    print("Scene: %d rooms, %.1f m2" % (scene.room_count, scene.total_floor_area_m2))

def cmd_styletransfer(args):
    from assistants.style_transfer import analyze_style_from_images, apply_style_to_scene
    scene = _load_scene(args.scene)
    analysis = analyze_style_from_images([args.reference])
    result = apply_style_to_scene(analysis, scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_daylight(args):
    from assistants.daylight_analysis import analyze_daylight
    result = analyze_daylight(args.scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_electrical(args):
    from assistants.electrical_plan import generate_electrical_plan
    result = generate_electrical_plan(args.scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_report(args):
    from export.to_report import generate_comprehensive_report
    result = generate_comprehensive_report(args.scene)
    print("Report: " + result)


def cmd_fengshui(args):
    """Fengshui analysis for floor plan"""
    from assistants.fengshui import analyze_fengshui
    scene = _load_scene(args.scene)
    result = analyze_fengshui(scene)
    output = args.output or "output/fengshui_report.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Fengshui: " + output)

def cmd_mep(args):
    """MEP (Mechanical/Electrical/Plumbing) plan"""
    from assistants.mep_planner import generate_mep_plan
    scene = _load_scene(args.scene)
    result = generate_mep_plan(scene)
    output = args.output or "output/mep_plan.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("MEP plan: " + output)

def cmd_smarthome(args):
    """Smart home plan"""
    from assistants.smart_home import generate_smart_home
    scene = _load_scene(args.scene) if args.scene else None
    result = generate_smart_home(scene)
    output = args.output or "output/smarthome.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Smart home: " + output)

def cmd_accessible(args):
    """Accessibility audit"""
    from assistants.accessibility import check_accessibility
    scene = _load_scene(args.scene)
    result = check_accessibility(scene)
    output = args.output or "output/accessibility.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("Accessibility: " + output)

def cmd_energy(args):
    """Energy efficiency analysis"""
    from core.energy_analysis import analyze_energy
    scene = _load_scene(args.scene) if args.scene else None
    result = analyze_energy(scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_diff(args):
    """Diff two scene versions"""
    from core.scene_diff import diff_scenes
    scene1 = _load_scene(args.scene1)
    scene2 = _load_scene(args.scene2)
    result = diff_scenes(scene1, scene2)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_cpm(args):
    """CPM construction schedule"""
    from core.cpm_scheduler import generate_schedule
    scene = _load_scene(args.scene) if args.scene else None
    result = generate_schedule(scene)
    output = args.output or "output/cpm_schedule.json"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("CPM schedule: " + output)

def cmd_waste(args):
    """Waste estimation"""
    from core.waste_estimator import estimate_waste
    scene = _load_scene(args.scene) if args.scene else None
    result = estimate_waste(scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_optimize(args):
    """Material optimization"""
    from core.material_optimizer import optimize_materials
    scene = _load_scene(args.scene) if args.scene else None
    result = optimize_materials(scene, args.budget)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_ventilation(args):
    """Ventilation analysis"""
    from assistants.ventilation_analysis import analyze_ventilation
    scene = _load_scene(args.scene)
    result = analyze_ventilation(scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_acoustic(args):
    """Acoustic analysis"""
    from assistants.acoustic_analysis import analyze_acoustics
    scene = _load_scene(args.scene)
    result = analyze_acoustics(scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])

def cmd_adjacency(args):
    """Room adjacency matrix"""
    from assistants.adjacency_matrix import analyze_adjacency
    scene = _load_scene(args.scene)
    result = analyze_adjacency(scene)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])


def cmd_all(args):
    """E2E full pipeline - AI-driven"""
    print("=" * 60)
    print("  Designer AI Automation Tool - Full Pipeline v3")
    print("=" * 60)

    out_dir = args.outdir or "output"
    os.makedirs(out_dir, exist_ok=True)

    # 1. Build scene
    print("\n[1/8] Building 3D scene...")
    if args.scan:
        scene = Scene3D.from_roomplan(args.scan)
    elif args.cad:
        scene = Scene3D.from_cad(args.cad)
    elif args.scene:
        scene = _load_scene(args.scene)
    else:
        print("ERROR: need --scan / --cad / --scene")
        return
    if args.conditions:
        cond = _load_conditions(args.conditions)
        scene.apply_design_conditions(cond)
    print("  Scene: %d rooms, %d walls, %.1f m2" % (scene.room_count, len(scene.walls), scene.total_floor_area_m2))

    # 2. Validate
    print("\n[2/8] Validating scene...")
    from core.validation_engine import validate_scene
    report = validate_scene(scene)
    print("  Score: %.0f/100 | Errors: %d | Warnings: %d" % (report.score, len(report.errors), len(report.warnings)))

    # 3. AI layout
    print("\n[3/8] AI furniture layout...")
    try:
        placements = apply_ai_layout(scene)
        print("  Placed %d furniture pieces (AI)" % len(placements))
    except Exception as e:
        print("  AI layout failed: %s, using rules" % e)
        apply_layout(scene)
        print("  Placed %d furniture pieces (rules)" % (len(scene.furniture) if hasattr(scene, "furniture") else 0))

    # 4. Floor plan
    print("\n[4/8] Generating floor plan...")
    generate_floor_plan(scene, os.path.join(out_dir, "floor_plan.dxf"), os.path.join(out_dir, "floor_plan.png"))
    print("  Floor plan -> %s/floor_plan.{dxf,png}" % out_dir)

    # 5. Budget
    print("\n[5/8] Calculating budget...")
    q, pricing = calculate_and_price(scene, args.region or "national_avg")
    export_budget_to_excel(pricing, os.path.join(out_dir, "budget.xlsx"))
    total = sum(it["total"] for it in pricing)
    print("  Total: %,.0f CNY -> %s/budget.xlsx" % (total, out_dir))

    # 6. Construction docs
    print("\n[6/8] Generating construction docs...")
    docs = generate_construction_docs(scene)
    dw = generate_door_window_schedule(scene)
    rs = generate_room_finish_schedule(scene)
    with open(os.path.join(out_dir, "construction_docs.json"), "w", encoding="utf-8") as f:
        json.dump({"docs": docs, "door_window": dw, "room_finish": rs}, f, ensure_ascii=False, indent=2)
    try:
        generate_all_drawings(scene, os.path.join(out_dir, "drawings"))
    except:
        pass
    print("  Construction docs -> %s/" % out_dir)

    # 7. Materials + checklist
    print("\n[7/8] Generating materials + checklists...")
    mats = generate_material_checklist(scene, scene.style)
    export_material_list_to_excel(mats, os.path.join(out_dir, "materials.xlsx"))
    checklist = generate_acceptance_checklist(scene)
    schedule = generate_construction_schedule(scene)
    export_schedule_to_excel(schedule, os.path.join(out_dir, "schedule.xlsx"))
    print("  Materials + checklists -> %s/" % out_dir)

    # 8. 3D preview + GLB
    print("\n[8/8] Generating 3D preview...")
    export_threejs_html(scene, os.path.join(out_dir, "3d_preview.html"))
    try:
        export_scene_to_gltf(scene, os.path.join(out_dir, "scene.glb"))
    except:
        pass
    print("  3D preview + GLB -> %s/" % out_dir)

    scene.save(os.path.join(out_dir, "scene.json"))

    print("\n" + "=" * 60)
    print("  E2E COMPLETE! Output: %s/" % out_dir)
    print("  floor_plan.{dxf,png} | budget.xlsx | materials.xlsx")
    print("  construction_docs.json | schedule.xlsx")
    print("  3d_preview.html | scene.json | scene.glb")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Designer AI Automation Tool v3")
    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser("template", help="Generate survey template")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("parse", help="Parse survey to design conditions")
    p.add_argument("input")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("cad", help="Read CAD DXF")
    p.add_argument("input")

    p = subparsers.add_parser("scan", help="Analyze RoomPlan scan")
    p.add_argument("input")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("build", help="Build 3D scene")
    p.add_argument("--scan")
    p.add_argument("--cad")
    p.add_argument("--scene")
    p.add_argument("--conditions", "-c")
    p.add_argument("--layout", "-l", action="store_true")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("floorplan", help="Generate floor plan")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--dxf")
    p.add_argument("--png")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("budget", help="Generate budget")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--region", "-r", default="national_avg")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("materials", help="Generate material list")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("layout", help="AI furniture layout")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("render", help="3D preview HTML")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("gltf", help="Export GLB model")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("docs", help="Construction docs")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("drawings", help="Construction drawings SVG")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("schedule", help="Construction schedule")
    p.add_argument("--scene", "-s")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("checklist", help="Acceptance checklist")
    p.add_argument("--scene", "-s")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("vision", help="VLM spatial analysis")
    p.add_argument("images", nargs="+")
    p.add_argument("--mode", choices=["room","style","qa"], default="room")
    p.add_argument("--provider", default="sensenova")
    p.add_argument("--question")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("cloudrender", help="Cloud render")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--config", default="interior_fast")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("ailayout", help="AI furniture layout")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("validate", help="Validate scene")
    p.add_argument("--scene", "-s", required=True)

    p = subparsers.add_parser("critique", help="Design critique")
    p.add_argument("scene")

    p = subparsers.add_parser("estimate", help="Cost estimate")
    p.add_argument("--scene", "-s")
    p.add_argument("--region", "-r", default="national_avg")

    p = subparsers.add_parser("photo2scene", help="Photos to 3D scene")
    p.add_argument("images", nargs="+")
    p.add_argument("--provider")
    p.add_argument("--no-vlm", action="store_true")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("styletransfer", help="Style transfer from reference image")
    p.add_argument("reference", help="Reference image path")
    p.add_argument("scene", help="Scene JSON path")
    p.add_argument("--output", "-o", help="Output path")

    p = subparsers.add_parser("daylight", help="Daylight analysis")
    p.add_argument("scene")

    p = subparsers.add_parser("electrical", help="Electrical plan")
    p.add_argument("scene")

    p = subparsers.add_parser("report", help="Full report")
    p.add_argument("scene")

    p = subparsers.add_parser("fengshui", help="Fengshui analysis")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("mep", help="MEP plan")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("smarthome", help="Smart home plan")
    p.add_argument("--scene", "-s")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("accessible", help="Accessibility audit")
    p.add_argument("--scene", "-s", required=True)
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("energy", help="Energy analysis")
    p.add_argument("--scene", "-s")

    p = subparsers.add_parser("diff", help="Scene diff")
    p.add_argument("scene1")
    p.add_argument("scene2")

    p = subparsers.add_parser("cpm", help="CPM schedule")
    p.add_argument("--scene", "-s")
    p.add_argument("--output", "-o")

    p = subparsers.add_parser("waste", help="Waste estimation")
    p.add_argument("--scene", "-s")

    p = subparsers.add_parser("optimize", help="Material optimization")
    p.add_argument("--scene", "-s")
    p.add_argument("--budget", type=float)

    p = subparsers.add_parser("ventilation", help="Ventilation analysis")
    p.add_argument("--scene", "-s", required=True)

    p = subparsers.add_parser("acoustic", help="Acoustic analysis")
    p.add_argument("--scene", "-s", required=True)

    p = subparsers.add_parser("adjacency", help="Adjacency matrix")
    p.add_argument("--scene", "-s", required=True)

    p = subparsers.add_parser("all", help="Full pipeline")
    p.add_argument("--scan")
    p.add_argument("--cad")
    p.add_argument("--scene")
    p.add_argument("--conditions", "-c")
    p.add_argument("--region", "-r", default="national_avg")
    p.add_argument("--outdir", "-o", default="output")

    args = parser.parse_args()
    commands = {
        "template": cmd_template, "parse": cmd_parse, "cad": cmd_cad,
        "scan": cmd_scan, "build": cmd_build, "floorplan": cmd_floorplan,
        "budget": cmd_budget, "materials": cmd_materials,
        "layout": cmd_layout, "render": cmd_render, "gltf": cmd_gltf,
        "docs": cmd_docs, "drawings": cmd_drawings,
        "schedule": cmd_schedule, "checklist": cmd_checklist,
        "vision": cmd_vision, "cloudrender": cmd_cloudrender,
        "ailayout": cmd_ailayout, "validate": cmd_validate,
        "critique": cmd_critique, "estimate": cmd_estimate,
        "photo2scene": cmd_photo2scene, "styletransfer": cmd_styletransfer,
        "daylight": cmd_daylight, "electrical": cmd_electrical,
        "report": cmd_report, "fengshui": cmd_fengshui,
        "mep": cmd_mep, "smarthome": cmd_smarthome, "accessible": cmd_accessible,
        "energy": cmd_energy, "diff": cmd_diff, "cpm": cmd_cpm,
        "waste": cmd_waste, "optimize": cmd_optimize,
        "ventilation": cmd_ventilation, "acoustic": cmd_acoustic,
        "adjacency": cmd_adjacency,
        "all": cmd_all,
    }
    if args.command in commands:
        commands[args.command](args)
    elif args.command is None:
        parser.print_help()
    else:
        print("Unknown command: " + args.command)
        parser.print_help()

if __name__ == "__main__":
    main()