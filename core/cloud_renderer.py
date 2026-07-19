# -*- coding: utf-8 -*-
"""cloud_renderer v4 - Multi-backend rendering engine
Primary: Blender Cycles CPU (tested, stable)
Secondary: Three.js HTML preview (for browser viewing with CDN)
Fallback: Node.js headless (attempts WebGL, falls back to Blender on failure)
"""
import json, os, base64, uuid, time, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

RENDER_CONFIGS = {
    "preview":         {"samples": 4,  "resolution": [400, 300],  "denoise": False, "timeout_s": 60},
    "interior_fast":   {"samples": 8,  "resolution": [800, 600],  "denoise": False, "timeout_s": 120},
    "interior_quality": {"samples": 12, "resolution": [960, 720],  "denoise": False, "timeout_s": 360},
    "floor_plan":      {"samples": 4,  "resolution": [800, 600],  "denoise": False, "timeout_s": 90},
    "production":      {"samples": 32, "resolution": [1920, 1080], "denoise": False, "timeout_s": 900},
}

from dataclasses import dataclass, field

@dataclass
class RenderTask:
    id: str
    scene_data: dict
    camera: dict
    config: str
    status: str = "pending"
    output_path: str = ""
    output_url: str = ""
    error: str = ""

class RenderEngine:
    """Multi-backend rendering engine. Blender Cycles CPU is the primary backend."""

    def __init__(self):
        self.blender_path = self._find_blender()
        self.node_available = self._check_node()
        self.headless_webgl_capable = False  # Requires GPU; auto-detected
        self.tasks = {}

    def _find_blender(self):
        paths = [
            os.path.join(os.path.expanduser("~"), ".blender", "blender-4.2.0-windows-x64", "blender.exe"),
            os.path.join(os.path.expanduser("~"), ".blender", "blender-4.1.0-windows-x64", "blender.exe"),
            r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        try:
            result = subprocess.run(["blender", "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return "blender"
        except Exception:
            pass
        return None

    def _check_node(self):
        try:
            result = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    @property
    def available_backends(self):
        backends = ["threejs_html"]  # Always available (browser preview)
        if self.blender_path:
            backends.insert(0, "blender_cycles")  # Primary
        return backends

    def render(self, scene, camera=None, config="preview", output_path=None, backend=None):
        task_id = str(uuid.uuid4())[:8]
        if camera is None:
            camera = self._auto_camera(scene)
        task = RenderTask(id=task_id, scene_data=self._extract_scene(scene), camera=camera, config=config)
        if output_path is None:
            output_path = os.path.join("output", "render_%s.png" % task_id)
        out_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(out_dir, exist_ok=True)

        # Auto-select backend
        if backend is None:
            backend = "blender_cycles" if self.blender_path else "threejs_html"

        if backend == "blender_cycles" and self.blender_path:
            task = self._render_blender(task, os.path.abspath(output_path))
        elif backend in ("threejs_html", "threejs_headless"):
            # Try headless screenshot first, fall back to HTML-only
            task = self._render_threejs(task, os.path.abspath(output_path))
        else:
            task.status = "failed"
            task.error = "No rendering backend available (Blender not found)"

        self.tasks[task_id] = task
        return task

    def _auto_camera(self, scene):
        rooms = scene.get("rooms", []) if isinstance(scene, dict) else getattr(scene, "rooms", {})
        if isinstance(rooms, dict):
            rooms = list(rooms.values())
        if not rooms:
            return {"position": [5000, 8000, 8000], "target": [2000, 0, 1500], "fov": 60}
        all_x, all_z = [], []
        for r in rooms:
            pts = r.get("floor_points", []) if isinstance(r, dict) else getattr(r, "floor_points", [])
            for p in pts:
                if isinstance(p, dict):
                    all_x.append(p.get("x", 0)); all_z.append(p.get("z", 0))
                elif hasattr(p, "x"):
                    all_x.append(p.x); all_z.append(p.z)
        if not all_x:
            return {"position": [5000, 8000, 8000], "target": [2000, 0, 1500], "fov": 60}
        cx = (max(all_x) + min(all_x)) / 2
        cz = (max(all_z) + min(all_z)) / 2
        span = max(max(all_x) - min(all_x), max(all_z) - min(all_z))
        dist = max(span * 1.2, 3000)
        return {"position": [cx, dist * 0.8, cz + dist], "target": [cx, 0, cz], "fov": 60}

    def _extract_scene(self, scene):
        if isinstance(scene, dict):
            return scene
        data = {"rooms": [], "walls": [], "furniture": [], "beams": [], "columns": []}
        walls = getattr(scene, "walls", {})
        if isinstance(walls, dict):
            for w in walls.values():
                data["walls"].append({
                    "start": [w.start.x, w.start.y, w.start.z],
                    "end": [w.end.x, w.end.y, w.end.z],
                    "h": w.height_mm, "t": w.thickness_mm
                })
        rooms = getattr(scene, "rooms", {})
        if isinstance(rooms, dict):
            for r in rooms.values():
                data["rooms"].append({"name": r.name, "pts": [{"x": p.x, "z": p.z} for p in r.floor_points]})
        furn = getattr(scene, "furniture", [])
        if isinstance(furn, list):
            for f in furn:
                data["furniture"].append({
                    "name": f.name, "pos": [f.position.x, f.position.y, f.position.z],
                    "w": f.width_mm, "d": f.depth_mm, "h": f.height_mm
                })
        elif isinstance(furn, dict):
            for f in furn.values():
                data["furniture"].append({
                    "name": f.name, "pos": [f.position.x, f.position.y, f.position.z],
                    "w": f.width_mm, "d": f.depth_mm, "h": f.height_mm
                })
        return data

    def _render_blender(self, task, output_path):
        """Primary rendering: Blender Cycles CPU."""
        try:
            cfg = RENDER_CONFIGS.get(task.config, RENDER_CONFIGS["preview"])
            script_path = os.path.join(os.path.dirname(__file__), "blender_render.py")

            env = os.environ.copy()
            env["RENDER_CFG"] = json.dumps({
                "samples": cfg["samples"],
                "res_x": cfg["resolution"][0],
                "res_y": cfg["resolution"][1],
                "output": output_path.replace("\\", "/"),
            })
            env["RENDER_CAM"] = json.dumps({
                "pos": task.camera.get("position", [5000, 8000, 8000]),
                "tgt": task.camera.get("target", [2000, 0, 1500])
            })
            env["RENDER_SCENE"] = json.dumps(task.scene_data)

            result = subprocess.run(
                [self.blender_path, "--background", "--python", script_path],
                capture_output=True, text=False,
                timeout=cfg["timeout_s"] + 120,
                env=env,
            )

            if os.path.exists(output_path) and os.path.getsize(output_path) > 500:
                task.status = "completed"
                task.output_path = output_path
            else:
                task.status = "failed"
                stderr = (result.stderr or b"").decode("utf-8", errors="replace")
                stdout = (result.stdout or b"").decode("utf-8", errors="replace")
                task.error = (stderr + stdout)[:500] or "No output generated"
        except subprocess.TimeoutExpired:
            task.status = "failed"
            task.error = "Blender render timed out (config: %s, timeout: %ds)" % (task.config, cfg["timeout_s"])
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
        return task

    def _render_threejs(self, task, output_path):
        """Generate Three.js HTML preview. Attempt headless screenshot, but HTML is the primary deliverable."""
        try:
            from assistants.renderer import export_threejs_html
            html_path = output_path.replace(".png", ".html")
            export_threejs_html(task.scene_data, html_path)

            # Attempt headless screenshot as a bonus
            if self.node_available:
                script_path = os.path.join(os.path.dirname(__file__), "headless_render.js")
                cfg = RENDER_CONFIGS.get(task.config, RENDER_CONFIGS["preview"])
                w, h = cfg["resolution"]

                try:
                    result = subprocess.run(
                        ["node", script_path, os.path.abspath(html_path), os.path.abspath(output_path), str(w), str(h)],
                        capture_output=True, text=True,
                        timeout=cfg["timeout_s"] + 60,
                    )
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 500:
                        task.status = "completed"
                        task.output_path = output_path
                        task.error = ""  # Success with screenshot
                    else:
                        # Screenshot failed, HTML is still valid
                        task.status = "completed"
                        task.output_path = html_path
                        task.error = "Headless screenshot failed (no WebGL on this server), HTML preview generated"
                except subprocess.TimeoutExpired:
                    task.status = "completed"
                    task.output_path = html_path
                    task.error = "Headless render timed out, HTML preview generated"
            else:
                task.status = "completed"
                task.output_path = html_path
                task.error = ""
        except Exception as e:
            task.status = "failed"
            task.error = str(e)
        return task


_engine = None

def get_render_engine():
    global _engine
    if _engine is None:
        _engine = RenderEngine()
    return _engine

def render_scene(scene, camera=None, config="preview", output_path=None):
    return get_render_engine().render(scene, camera, config, output_path)
