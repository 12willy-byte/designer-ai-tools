#!/usr/bin/env python3
\"\"\"设计师AI辅助自动化工具 CLI\"\"\"
import sys, os, json

def cmd_sample():
    from core.scene3d import Scene3D
    return Scene3D.from_roomplan('templates/sample_roomplan.json')

def cmd_text(path):
    with open(path, 'r', encoding='utf-8') as f: rooms = json.load(f)
    from core.image2scene_enhanced import text_to_scene
    return text_to_scene(rooms)

def cmd_cad(path):
    from core.scene3d import Scene3D
    return Scene3D.from_cad(path)

def cmd_photo(paths):
    from assistants.vlm_analyzer import VLMImageAnalyzer
    analyzer = VLMImageAnalyzer()
    return analyzer.photos_to_scene(paths)

def run_pipeline(scene, style='modern', out_dir='output/latest'):
    from core.auto_layout_engine import auto_furnish, assign_materials
    from assistants.renderer import export_threejs_html
    from export.to_gltf import GLTFExporter
    from core.pricing_engine_v2 import estimate_full_budget

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(f'{out_dir}/renders', exist_ok=True)
    os.makedirs(f'{out_dir}/drawings', exist_ok=True)

    print(f'Scene: {len(scene.walls)}walls {len(scene.rooms)}rooms')

    auto_furnish(scene, style=style, use_ai=False)

    assign_materials(scene, style=style)

    budget = estimate_full_budget(scene)
    json.dump(budget, open(f'{out_dir}/budget.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)

    json.dump(scene.to_dict(), open(f'{out_dir}/scene.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)

    GLTFExporter(scene).export(f'{out_dir}/scene.glb')
    export_threejs_html(scene, f'{out_dir}/3d_preview.html')

    from core.cloud_renderer import render_scene
    for cfg in ['preview','standard','topdown']:
        render_scene(scene, config=cfg, output_path=f'{out_dir}/renders/{cfg}.png')

    from assistants.construction_drawings import generate_all_drawings
    generate_all_drawings(scene.to_dict(), f'{out_dir}/drawings')

    from assistants.floor_plan_generator import generate_floor_plan
    generate_floor_plan(scene, f'{out_dir}/floor_plan.dxf')

    print(f'DONE total={budget[\"summary\"][\"total\"]:,} CNY -> {out_dir}')
    return {'id': os.path.basename(out_dir), 'files': os.listdir(out_dir), 'budget': budget}

def main():
    if len(sys.argv) < 2:
        print('Usage: python main.py sample|text|cad|photo <path...>')
        return

    cmd = sys.argv[1]
    style = 'modern'
    out = f'output/{cmd}'

    if cmd == 'sample':
        scene = cmd_sample()
    elif cmd == 'text' and len(sys.argv) > 2:
        scene = cmd_text(sys.argv[2])
    elif cmd == 'cad' and len(sys.argv) > 2:
        scene = cmd_cad(sys.argv[2])
    elif cmd == 'photo' and len(sys.argv) > 2:
        scene = cmd_photo(sys.argv[2:])
    else:
        print(f'Unknown: {cmd}')
        return

    run_pipeline(scene, style=style, out_dir=out)

if __name__ == '__main__':
    main()
