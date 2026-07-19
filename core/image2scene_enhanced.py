import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene3d import Scene3D, Wall, Room, Opening, OpeningType, Point3D

def text_to_scene(rooms, name='My Project'):
    scene = Scene3D(name=name); cx = 0; wc = 0
    for room in rooms:
        rn = room.get('name','room'); rt = room.get('type','living')
        l = room.get('length_mm',4000); w = room.get('width_mm',3500); h = room.get('height_mm',2800)
        wids = []
        for (sx,sz,ex,ez) in [(cx,0,cx,w),(cx+l,0,cx+l,w),(cx,0,cx+l,0),(cx,w,cx+l,w)]:
            wid = f'wall-{wc}'; wids.append(wid); wc += 1
            scene.walls[wid] = Wall(id=wid, start=Point3D(x=sx,y=0,z=sz), end=Point3D(x=ex,y=0,z=ez), height_mm=h)
        for d in room.get('doors',[]):
            dw = scene.walls[wids[d.get('wall',0)]]
            dw.openings.append(Opening(id=f'door-{rn}-{len(dw.openings)}', type=OpeningType.DOOR, offset_mm=d.get('offset',l/2-400), width_mm=d.get('width',900), height_mm=d.get('height',2100)))
        for wi in room.get('windows',[]):
            ww = scene.walls[wids[wi.get('wall',2)]]
            ww.openings.append(Opening(id=f'window-{rn}-{len(ww.openings)}', type=OpeningType.WINDOW, offset_mm=wi.get('offset',l/2-600), width_mm=wi.get('width',1500), height_mm=wi.get('height',1500), sill_height_mm=wi.get('sill_height',900)))
        fps = [Point3D(x=cx,y=0,z=0), Point3D(x=cx+l,y=0,z=0), Point3D(x=cx+l,y=0,z=w), Point3D(x=cx,y=0,z=w)]
        robj = Room(id=f'room-{rn}', name=rn, wall_ids=wids, floor_points=fps, ceiling_height_mm=h)
        robj.requirements = {'type': rt, 'area_m2': l*w/1e6}
        scene.rooms[robj.id] = robj
        cx += l + 240
    return scene

def quick_pipeline(rooms, style='modern', out='output/quick'):
    from core.auto_layout_engine import auto_furnish, assign_materials, generate_budget_all
    from assistants.renderer import export_threejs_html
    from export.to_gltf import GLTFExporter
    os.makedirs(out, exist_ok=True); os.makedirs(f'{out}/renders', exist_ok=True); os.makedirs(f'{out}/drawings', exist_ok=True)
    scene = text_to_scene(rooms)
    print(f'Scene: {len(scene.walls)}w {len(scene.rooms)}r')
    auto_furnish(scene, style=style, use_ai=False)
    assign_materials(scene, style=style)
    budget = generate_budget_all(scene)
    json.dump(budget, open(f'{out}/budget.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump(scene.to_dict(), open(f'{out}/scene.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
    GLTFExporter(scene).export(f'{out}/scene.glb')
    export_threejs_html(scene, f'{out}/3d_preview.html')
    from core.cloud_renderer import render_scene
    render_scene(scene, config='preview', output_path=f'{out}/renders/preview.png')
    render_scene(scene, config='standard', output_path=f'{out}/renders/quality.png')
    render_scene(scene, config='topdown', output_path=f'{out}/renders/topdown.png')
    from assistants.construction_drawings import generate_all_drawings
    generate_all_drawings(scene.to_dict(), f'{out}/drawings')
    from assistants.floor_plan_generator import generate_floor_plan
    generate_floor_plan(scene, f'{out}/floor_plan.dxf')
    print(f'Pipeline DONE -> {out}')
    return scene

print('image2scene_enhanced v2 ready')
