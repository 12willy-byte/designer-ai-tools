# -*- coding: utf-8 -*-
"""
web_server - HTTP API server for the Designer AI web dashboard
Provides: /api/run, /api/demo, /api/status, /api/download
"""
import json, os, sys, io, zipfile, shutil, base64
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(__file__))
from core.scene3d import Scene3D
from core.ai_client import get_client, reset_client
from core.validation_engine import validate_scene
from core.pricing_engine import estimate_total_cost
from assistants.design_critique import critique_design
from assistants.electrical_plan import generate_electrical_plan
from assistants.furniture_layout_ai import apply_ai_layout
from assistants.daylight_analysis import analyze_daylight, generate_lighting_plan
from assistants.construction_drawings import generate_all_drawings
from core.cpm_scheduler import generate_schedule
from core.scene_utils import get_rooms
from export.to_report import generate_comprehensive_report
from core.project_dashboard import generate_dashboard, save_dashboard

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def run_full_pipeline(scene_data=None, style="modern_minimalist", region="二线"):
    """Run the complete pipeline and return dashboard data."""
    
    # Load scene
    if scene_data and os.path.exists(scene_data):
        scene = Scene3D.from_roomplan(scene_data)
    else:
        # Use sample data
        sample = os.path.join(os.path.dirname(__file__), "templates", "sample_roomplan.json")
        if os.path.exists(sample):
            scene = Scene3D.from_roomplan(sample)
        else:
            # Create minimal scene
            scene = Scene3D(name="Demo Project")
    
    rooms = get_rooms(scene)
    
    # Run all analyses
    validation = validate_scene(scene)
    cost = estimate_total_cost(scene, region, "standard")
    critique = critique_design(scene)
    electrical = generate_electrical_plan(scene)
    schedule = generate_schedule(scene)
    daylight = analyze_daylight(scene)
    layout_count = len(apply_ai_layout(scene))
    
    # Generate outputs
    out = os.path.join(OUTPUT_DIR, "demo")
    os.makedirs(out, exist_ok=True)
    
    try:
        generate_all_drawings(scene, out)
    except: pass
    
    try:
        generate_comprehensive_report(scene, os.path.join(out, "report.html"))
    except: pass
    
    scene.save(os.path.join(out, "scene.json"))
    
    # Build dashboard
    dashboard = generate_dashboard(scene,
        validation=validation, cost=cost, critique=critique,
        electrical=electrical, schedule=schedule, daylight=daylight,
        layout_count=layout_count,
    )
    save_dashboard(dashboard, os.path.join(out, "dashboard.json"))
    
    # Simplified response for web
    total_area = sum(r.area_m2 for r in rooms) if hasattr(rooms[0], 'area_m2') if rooms else 0
    
    return {
        "success": True,
        "rooms": len(rooms),
        "area": round(total_area, 1),
        "cost": round(cost['summary']['grand_total']),
        "cost_per_sqm": round(cost['summary']['per_sqm']),
        "critique_score": critique.score,
        "critique_items": [
            {"cat": i.cat, "sev": i.sev.value if hasattr(i.sev, 'value') else str(i.sev), 
             "title": i.title} for i in critique.items[:10]
        ],
        "validation": validation.score,
        "layout": layout_count,
        "electrical": len(electrical.points),
        "schedule": schedule.total_days,
        "ai_available": get_client().available,
        "output_dir": out,
    }

class APIHandler(SimpleHTTPRequestHandler):
    """Custom handler serving web/ directory and API endpoints."""
    
    def __init__(self, *args, **kwargs):
        self.directory = os.path.join(os.path.dirname(__file__), "web")
        super().__init__(*args, directory=self.directory, **kwargs)
    
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/api/status":
            self._json({"ai_available": get_client().available, "server": "running"})
        elif parsed.path == "/api/download":
            self._download_zip()
        elif parsed.path == "/api/demo":
            self.do_POST()  # Demo uses same pipeline
        else:
            # Serve static files from web/
            super().do_GET()
    
    def do_POST(self):
        parsed = urlparse(self.path)
        
        if parsed.path in ("/api/run", "/api/demo"):
            try:
                result = run_full_pipeline()
                self._json(result)
            except Exception as e:
                self._json({"success": False, "error": str(e)}, 500)
        else:
            self._json({"error": "Not found"}, 404)
    
    def _json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode())
    
    def _download_zip(self):
        """Zip and download all output files."""
        out_dir = os.path.join(OUTPUT_DIR, "demo")
        zip_path = os.path.join(OUTPUT_DIR, "deliverables.zip")
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(out_dir):
                for root, dirs, files in os.walk(out_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        an = os.path.relpath(fp, out_dir)
                        zf.write(fp, an)
        
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", "attachment; filename=deliverables.zip")
        self.end_headers()
        with open(zip_path, 'rb') as f:
            self.wfile.write(f.read())

def main():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    print(f"Designer AI Server: http://localhost:{port}")
    print(f"Web UI: http://localhost:{port}/index.html")
    print(f"API: http://localhost:{port}/api/status")
    print(f"AI Available: {get_client().available}")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()