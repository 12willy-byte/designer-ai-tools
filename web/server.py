import os,sys,json,http.server
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(s):
        if s.path=="/api/status":s.do_json({"ready":True})
        else:super().do_GET()
    def do_POST(s):
        if s.path=="/api/generate":
            d=json.loads(s.rfile.read(int(s.headers["Content-Length"])))
            out="output/latest";os.makedirs(out,exist_ok=True)
            from core.image2scene_enhanced import text_to_scene as t2s
            from core.auto_layout_engine import auto_furnish as af,assign_materials as am
            from core.pricing_engine_v2 import estimate_full_budget as efb
            sc=t2s(d["rooms"]);af(sc,"modern",False);am(sc,"modern")
            b=efb(sc)
            json.dump(b,open(out+"/budget.json","w",encoding="utf-8"),ensure_ascii=False,indent=2)
            json.dump(sc.to_dict(),open(out+"/scene.json","w",encoding="utf-8"),ensure_ascii=False,indent=2)
            from assistants.renderer import export_threejs_html;export_threejs_html(sc,out+"/3d_preview.html")
            from assistants.construction_drawings import generate_all_drawings;generate_all_drawings(sc.to_dict(),out+"/drawings")
            from assistants.floor_plan_generator import generate_floor_plan;generate_floor_plan(sc,out+"/floor_plan.dxf")
            from export.to_gltf import GLTFExporter;GLTFExporter(sc).export(out+"/scene.glb")
            os.makedirs(out+"/renders",exist_ok=True)
            from core.cloud_renderer import render_scene;render_scene(sc,config="preview",output_path=out+"/renders/preview.png")
            s.do_json({"id":"latest","files":os.listdir(out),"budget":b})
        else:s.send_response(404);s.end_headers()
    def do_json(s,data):
        s.send_response(200);s.send_header("Content-Type","application/json");s.end_headers()
        s.wfile.write(json.dumps(data).encode())
def run(p=8080):
    os.chdir(os.path.dirname(os.path.dirname(__file__)))
    s=http.server.HTTPServer(("0.0.0.0",p),H)
    print(f"Server: http://localhost:{p}")
    s.serve_forever()
