"""统一管线 - 全流程一键执行，含SVG→PNG"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def run(scene, style="modern", out_dir="output/latest"):
    """全流程管线：场景→布局→材质→预算→渲染→施工图→SVG转PNG→导出"""
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(f"{out_dir}/renders", exist_ok=True)
    os.makedirs(f"{out_dir}/drawings", exist_ok=True)

    from core.auto_layout_engine import auto_furnish, assign_materials
    from core.pricing_engine_v2 import estimate_full_budget
    from assistants.renderer import export_threejs_html
    from export.to_gltf import GLTFExporter

    print(f"[1/8] Scene: {len(scene.walls)} walls, {len(scene.rooms)} rooms")

    auto_furnish(scene, style=style, use_ai=False)
    print(f"[2/8] Furniture placed")

    assign_materials(scene, style=style)
    print(f"[3/8] Materials assigned")

    budget = estimate_full_budget(scene)
    json.dump(budget, open(f"{out_dir}/budget.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[4/8] Budget: {budget['summary']['total']:,} CNY")

    json.dump(scene.to_dict(), open(f"{out_dir}/scene.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    GLTFExporter(scene).export(f"{out_dir}/scene.glb")
    export_threejs_html(scene, f"{out_dir}/3d_preview.html")
    print(f"[5/8] Scene exported (JSON + GLB + HTML)")

    from core.cloud_renderer import render_scene
    for cfg, name in [("preview","preview"),("standard","quality"),("topdown","topdown")]:
        render_scene(scene, config=cfg, output_path=f"{out_dir}/renders/{name}.png")
    print(f"[6/8] Renderings done")

    from assistants.construction_drawings import generate_all_drawings
    from assistants.floor_plan_generator import generate_floor_plan
    generate_all_drawings(scene.to_dict(), f"{out_dir}/drawings")
    generate_floor_plan(scene, f"{out_dir}/floor_plan.dxf")
    print(f"[7/8] Construction drawings + DXF")

    # SVG → PNG conversion
    svg_dir = f"{out_dir}/drawings"
    png_count = 0
    try:
        from core.svg_to_png_pil import svg_to_png
        for f in sorted(os.listdir(svg_dir)):
            if f.endswith(".svg"):
                svg_path = os.path.join(svg_dir, f)
                png_path = svg_path.replace(".svg", ".png")
                try:
                    svg_to_png(svg_path, png_path, scale=3)
                    png_count += 1
                except Exception as e:
                    print(f"  PNG skip {f}: {e}")
    except ImportError:
        print("  SVG→PNG: PIL/lxml not available, skipping")
    print(f"[8/8] SVG→PNG: {png_count} converted")

    print(f"\n=== PIPELINE DONE ===")
    print(f"  Output: {out_dir}/")
    print(f"  Budget: {budget['summary']['total']:,} CNY")
    print(f"  Files: {len(os.listdir(out_dir))} items")
    return {"dir": out_dir, "budget": budget, "png_converted": png_count}

print("pipeline v1 ready")
