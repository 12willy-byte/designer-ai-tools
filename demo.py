# -*- coding: utf-8 -*-
"""
demo.py - One-click end-to-end demonstration
Runs the FULL pipeline and opens the web dashboard.
Usage: python demo.py
"""
import json, os, sys, webbrowser, subprocess, time

sys.path.insert(0, os.path.dirname(__file__))

def banner():
    print("""
╔══════════════════════════════════════════════╗
║        Designer AI Assistant v5              ║
║      3D Scene is the Single Source of Truth  ║
╚══════════════════════════════════════════════╝
    """)

def step(n, total, name):
    print(f"  [{n}/{total}] {name}...", end=" ", flush=True)

def ok(msg=""):
    print(f"OK {msg}")

def fail(msg=""):
    print(f"FAIL {msg}")

def main():
    banner()
    
    from core.scene3d import Scene3D, Room, Wall, Point3D, Opening, OpeningType
    from core.ai_client import get_client
    from core.validation_engine import validate_scene, print_validation_report
    from core.pricing_engine import estimate_total_cost
    from assistants.design_critique import critique_design, print_critique
    from assistants.electrical_plan import generate_electrical_plan, print_electrical_plan
    from assistants.furniture_layout_ai import apply_ai_layout
    from assistants.daylight_analysis import analyze_daylight, generate_lighting_plan, daylight_report
    from assistants.construction_drawings import generate_all_drawings
    from assistants.fengshui import analyze_fengshui, print_fengshui
    from assistants.fire_safety import check_fire_safety, print_fire_report
    from assistants.accessibility import check_accessibility, print_acc_report
    from assistants.acoustic_analysis import analyze_acoustics, print_acoustic_report
    from assistants.adjacency_matrix import analyze_adjacency, print_adjacency
    from assistants.mep_planner import generate_mep_plan, print_mep_plan
    from assistants.smart_home import generate_smart_home, print_smart_home
    from assistants.style_transfer import analyze_style_from_images, generate_style_guide
    from core.cpm_scheduler import generate_schedule, print_schedule
    from core.energy_analysis import analyze_energy
    from core.waste_estimator import estimate_waste, print_waste
    from core.material_optimizer import optimize_materials
    from core.scene_diff import diff_scenes, print_diff
    from core.project_dashboard import generate_dashboard, save_dashboard
    from export.to_report import generate_comprehensive_report
    from export.to_gltf import export_scene_to_gltf
    from assistants.renderer import export_threejs_html
    
    TOTAL = 20
    out = "output/demo"
    os.makedirs(out, exist_ok=True)
    
    # 1. AI Status
    step(1, TOTAL, "AI client")
    ai = get_client()
    ok(f"provider={ai.config.provider}, available={ai.available}")
    
    # 2. Build demo scene
    step(2, TOTAL, "Build demo scene")
    scene = Scene3D(name="Demo Project - 2BR Apartment")
    
    rdata = [
        ("r1","Living Room","living_room", 5500, 4200),
        ("r2","Master Bedroom","bedroom", 4200, 3600),
        ("r3","Second Bedroom","bedroom", 3600, 3000),
        ("r4","Kitchen","kitchen", 3000, 2500),
        ("r5","Bathroom","bathroom", 2500, 2200),
        ("r6","Entry Hall","hallway", 2000, 1800),
    ]
    for rid, name, rtype, l, w in rdata:
        r = Room(id=rid, name=name, type=rtype,
                 floor_points=[Point3D(0,0,0),Point3D(l,0,0),Point3D(l,0,w),Point3D(0,0,w)],
                 ceiling_height_mm=2800)
        scene.rooms[rid] = r
    
    for i, (rid, name, rtype, l, w) in enumerate(rdata):
        w1 = Wall(id=f"w{i}a", start=Point3D(0,0,0), end=Point3D(l,0,0), height_mm=2800, thickness_mm=120, room_id=rid)
        w2 = Wall(id=f"w{i}b", start=Point3D(l,0,0), end=Point3D(l,0,w), height_mm=2800, thickness_mm=120, room_id=rid)
        scene.walls[w1.id] = w1; scene.walls[w2.id] = w2
        
        op = Opening(id=f"d{i}", type=OpeningType.DOOR, offset_mm=int(l*0.5), width_mm=900, height_mm=2100)
        w1.openings.append(op); scene.doors[op.id] = op
        
        if rtype in ('bedroom','living_room'):
            op2 = Opening(id=f"win{i}", type=OpeningType.WINDOW, offset_mm=int(l*0.3), width_mm=1800, height_mm=1500, sill_height_mm=900)
            w2.openings.append(op2); scene.windows[op2.id] = op2
    
    room_count = len(getattr(scene, 'rooms', {}))
    area = sum(r.area_m2 for r in getattr(scene, 'rooms', {}).values())
    ok(f"{room_count} rooms, {area:.1f}m2")
    
    # 3. Validation
    step(3, TOTAL, "Validation")
    val = validate_scene(scene)
    ok(f"score={val.score:.0f}")
    
    # 4. Design Critique
    step(4, TOTAL, "Design Critique")
    cr = critique_design(scene)
    ok(f"score={cr.score:.0f}")
    
    # 5. Cost
    step(5, TOTAL, "Cost Estimation")
    cost = estimate_total_cost(scene, "二线", "standard")
    ok(f"total=RMB {cost['summary']['grand_total']:,.0f}")
    
    # 6. Electrical
    step(6, TOTAL, "Electrical Plan")
    elec = generate_electrical_plan(scene)
    ok(f"points={len(elec.points)}")
    
    # 7. Furniture Layout
    step(7, TOTAL, "Furniture Layout")
    layout = apply_ai_layout(scene)
    ok(f"pieces={len(layout)}")
    
    # 8. Daylight
    step(8, TOTAL, "Daylight Analysis")
    dl = analyze_daylight(scene)
    lp = generate_lighting_plan(dl)
    ok(f"rooms={len(dl)}")
    
    # 9. MEP
    step(9, TOTAL, "MEP Plan")
    mep = generate_mep_plan(scene)
    ok(f"plumbing={len(mep.plumbing)}, hvac={len(mep.hvac)}")
    
    # 10. Feng Shui
    step(10, TOTAL, "Feng Shui")
    fs = analyze_fengshui(scene)
    ok(f"good={fs.good_count}, bad={fs.bad_count}")
    
    # 11. Fire Safety
    step(11, TOTAL, "Fire Safety")
    fr = check_fire_safety(scene)
    ok(f"pass={fr.pass_count}/{len(fr.checks)}")
    
    # 12. Accessibility
    step(12, TOTAL, "Accessibility")
    acc = check_accessibility(scene)
    ok(f"score={acc.score}")
    
    # 13. Acoustics
    step(13, TOTAL, "Acoustics")
    ac = analyze_acoustics(scene)
    ok(f"pass={ac.overall_pass}")
    
    # 14. Adjacency
    step(14, TOTAL, "Adjacency")
    adj = analyze_adjacency(scene)
    ok(f"affinity={adj.total_affinity}/{adj.max_possible}")
    
    # 15. Smart Home
    step(15, TOTAL, "Smart Home")
    sh = generate_smart_home(scene)
    ok(f"devices={sh.total_devices}")
    
    # 16. CPM Schedule
    step(16, TOTAL, "Schedule")
    sch = generate_schedule(scene)
    ok(f"days={sch.total_days}")
    
    # 17. Energy
    step(17, TOTAL, "Energy")
    en = analyze_energy(scene)
    ok(f"heat={en.heating_load_kw}kW")
    
    # 18. Waste
    step(18, TOTAL, "Waste")
    wr = estimate_waste(scene)
    ok(f"weight={wr.total_weight_kg}kg")
    
    # 19. Drawings + Reports
    step(19, TOTAL, "Drawings & Reports")
    generate_all_drawings(scene, out)
    generate_comprehensive_report(scene, f"{out}/report.html")
    export_scene_to_gltf(scene, f"{out}/scene.glb")
    export_threejs_html(scene, f"{out}/3d_preview.html")
    dashboard = generate_dashboard(scene, validation=val, cost=cost, critique=cr,
        electrical=elec, layout_count=len(layout), daylight=dl, energy=en,
        fire=fr, accessibility=acc, acoustic=ac, fengshui=fs, schedule=sch,
        smart_home=sh, waste=wr, adjacency=adj, mep=mep,
    )
    save_dashboard(dashboard, f"{out}/dashboard.json")
    ok()
    
    # 20. Style Transfer
    step(20, TOTAL, "Style Transfer")
    style = analyze_style_from_images([])
    ok(f"style={style['style_analysis']['primary_style']}")
    
    # Summary
    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Output: {out}/")
    files = []
    for root, dirs, fnames in os.walk(out):
        for f in fnames:
            fp = os.path.join(root, f)
            files.append(f"  {os.path.relpath(fp, out)} ({os.path.getsize(fp)}b)")
    for f in sorted(files)[:15]:
        print(f)
    if len(files) > 15:
        print(f"  ... and {len(files)-15} more files")
    
    print(f"\n  Dashboard: {out}/dashboard.json")
    print(f"  Report: {out}/report.html")
    print(f"  3D Preview: {out}/3d_preview.html")
    print(f"{'='*60}")
    
    return dashboard

if __name__ == "__main__":
    main()