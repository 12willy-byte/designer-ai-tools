# -*- coding: utf-8 -*-
"""image2scene v2 - VLM-driven photo-to-3D-scene reconstruction
Uses Vision LLM (DeepSeek/OpenAI/SenseNova) to analyze room photos,
extract spatial structure, and build a Scene3D with proper geometry.
"""
import json, os, uuid, math, sys
import numpy as np
from PIL import Image
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.ai_client import get_client

# ============================================================
# CV pre-processing (lightweight, no GPU needed)
# ============================================================

# Try loading ONNX depth model (lightweight, no PyTorch needed)
_depth_model = None
_depth_model_name = None

def _load_depth_model():
    """Load ONNX-based depth estimation model if available."""
    global _depth_model, _depth_model_name
    if _depth_model is not None:
        return _depth_model
    
    # Try ONNX MiDaS or similar
    try:
        import onnxruntime as ort
        # Check for pre-downloaded model
        model_paths = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "depth_model.onnx"),
            os.path.expanduser("~/.cache/depth_model.onnx"),
        ]
        for mp in model_paths:
            if os.path.exists(mp):
                _depth_model = ort.InferenceSession(mp)
                _depth_model_name = os.path.basename(mp)
                print("[Image2Scene] Loaded depth model: %s" % _depth_model_name)
                return _depth_model
    except ImportError:
        pass
    except Exception as e:
        print("[Image2Scene] ONNX depth model load failed: %s" % e)
    
    return None


def estimate_depth(image_path):
    """Depth estimation with auto-selection of best available method.
    Priority: 1) ONNX depth model 2) OpenCV stereo 3) Heuristic fallback."""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    arr = np.array(img, dtype=np.float32)
    
    # Method 1: ONNX depth model
    model = _load_depth_model()
    if model is not None:
        try:
            import cv2
            input_name = model.get_inputs()[0].name
            # Resize to model expected size (typically 384x384)
            input_img = cv2.resize(arr, (128, 128)).transpose(2, 0, 1).astype(np.float32) / 255.0
            input_img = input_img[np.newaxis, ...]
            output = model.run(None, {input_name: input_img})[0]
            depth = cv2.resize(output[0], (w, h))
            depth = (depth - depth.min()) / (depth.max() - depth.min() + 1e-8)
            return {"depth_map": depth.tolist(), "width": w, "height": h, "min_m": 0.3, "max_m": 8.0, "method": "onnx_depth_model"}
        except Exception as e:
            print("[Image2Scene] ONNX inference failed: %s" % e)
    
    # Method 2: OpenCV-based structure-from-motion cues
    try:
        import cv2
        gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            # Use gradient magnitude as depth cue
            grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            gradient = np.sqrt(grad_x**2 + grad_y**2)
            gradient = cv2.GaussianBlur(gradient, (21, 21), 0)
            
            # Vertical position bias (floor is closer, ceiling is farther)
            y_coords = np.arange(h).reshape(-1, 1) / h
            brightness = gray.astype(np.float32) / 255.0
            
            # Combine cues
            depth = (1.0 - y_coords) * 0.4 + (1.0 - brightness) * 0.2
            depth = depth + (gradient / (gradient.max() + 1e-8)) * 0.4
            depth = np.clip(depth, 0.0, 1.0)
            return {"depth_map": depth.tolist(), "width": w, "height": h, "min_m": 0.3, "max_m": 8.0, "method": "opencv_gradient"}
    except ImportError:
        pass
    
    # Method 3: Pure heuristic (always works)
    y_coords = np.arange(h).reshape(-1, 1) / h
    brightness = arr.mean(axis=2) / 255.0
    grad_x = np.abs(np.diff(brightness, axis=1, append=brightness[:,-1:]))
    depth = (1.0 - y_coords) * 0.5 + (1.0 - brightness) * 0.3 + grad_x * 0.2
    depth = np.clip(depth, 0.0, 1.0)
    return {"depth_map": depth.tolist(), "width": w, "height": h, "min_m": 0.3, "max_m": 8.0, "method": "heuristic"}

def detect_vanishing_points(image_path):
    """Detect lines and vanishing points using Canny + Hough."""
    try:
        import cv2
        img = cv2.imread(image_path)
        if img is None:
            return {"error": "read failed"}
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 80, minLineLength=w//4, maxLineGap=w//10)
        if lines is None:
            return {"num_lines": 0, "is_interior": False}
        return {
            "num_lines": len(lines),
            "is_interior": len(lines) > 10,
            "width": w, "height": h,
        }
    except ImportError:
        return {"num_lines": 0, "is_interior": False, "note": "opencv not installed"}

# ============================================================
# VLM spatial analysis
# ============================================================

SPATIAL_SYSTEM = """You are an expert architectural space analyzer.
Examine interior photos and extract precise spatial information.
Use door height (~2100mm) as primary scale reference.
Estimate dimensions conservatively - typical rooms are 3-6m per side.
Output ONLY valid JSON without any markdown formatting."""

SPATIAL_PROMPT = """Analyze this interior photo. Output JSON:
{
  "room_type": "living_room/kitchen/bedroom/bathroom/hallway/balcony/study",
  "estimated_dimensions": {"length_mm": 5000, "width_mm": 4000, "height_mm": 2800},
  "structural_elements": {
    "walls": [{"position": "north/south/east/west", "length_mm": 5000}],
    "doors": [{"position": "north/south/east/west", "width_mm": 900, "height_mm": 2100}],
    "windows": [{"position": "north/south/east/west", "width_mm": 1500, "height_mm": 1500, "sill_height_mm": 900}],
    "columns": [],
    "beams": []
  },
  "floor_material": "tile/wood/concrete",
  "ceiling_type": "flat/coffered/exposed",
  "natural_light": "north/south/east/west/none",
  "confidence": 0.85
}
Use door height ~2100mm as reference. Be conservative with estimates."""

@dataclass
class ImageAnalysisResult:
    image_path: str = ""
    depth: dict = field(default_factory=dict)
    vanishing_points: dict = field(default_factory=dict)
    spatial_reasoning: dict = field(default_factory=dict)
    quality_score: float = 0.0

def analyze_single_photo(image_path, vlm_result=None):
    """Analyze a single photo with CV + optional VLM."""
    r = ImageAnalysisResult(image_path=image_path)
    r.depth = estimate_depth(image_path)
    r.vanishing_points = detect_vanishing_points(image_path)
    if vlm_result:
        r.spatial_reasoning = vlm_result
    vp = r.vanishing_points
    score = 0.2  # base score
    if vp.get("num_lines", 0) > 20:
        score += 0.3
    if vp.get("is_interior"):
        score += 0.3
    if vlm_result and vlm_result.get("confidence", 0) > 0.7:
        score += 0.2
    r.quality_score = min(score, 1.0)
    return r

def analyze_with_vlm(image_paths, provider=None):
    """Use VLM to analyze room photos for spatial structure."""
    client = get_client(provider)
    if not client.available:
        print("[Image2Scene] No AI available, using heuristics")
        return None
    
    all_results = []
    for path in image_paths:
        try:
            result = client.vision_json(path, SPATIAL_PROMPT, SPATIAL_SYSTEM)
            all_results.append(result)
            print("[Image2Scene] VLM analyzed: %s -> %s (confidence: %.2f)" % (
                os.path.basename(path), result.get("room_type", "?"), result.get("confidence", 0)))
        except Exception as e:
            print("[Image2Scene] VLM failed for %s: %s" % (path, e))
            all_results.append(None)
    
    return all_results

# ============================================================
# Scene3D construction
# ============================================================

def generate_scene_from_photos(photo_paths, room_names=None, vlm_analysis=None, output_path=None):
    """Build a Scene3D from photos with VLM analysis.
    
    Args:
        photo_paths: list of image paths
        room_names: optional list of room names
        vlm_analysis: pre-computed VLM results (or None to auto-detect)
        output_path: optional JSON output path
    
    Returns:
        Scene3D object
    """
    from core.scene3d import Scene3D, Room, Wall, Opening, OpeningType, Point3D
    
    # Auto-analyze with VLM if not provided
    if vlm_analysis is None:
        vlm_analysis = analyze_with_vlm(photo_paths)
    
    # Determine room names
    if not room_names:
        room_names = []
        if vlm_analysis:
            for v in vlm_analysis:
                if v and not v.get("parse_error"):
                    n = v.get("room_type", "room")
                    if n not in room_names:
                        room_names.append(n)
        if not room_names:
            room_names = ["room_%d" % (i+1) for i in range(len(photo_paths))]
    
    scene = Scene3D(name="Photo import - %d rooms" % len(photo_paths))
    
    # Default dimensions per room type
    defaults = {
        "living_room": (5.0, 4.0), "bedroom": (4.0, 3.5),
        "kitchen": (3.5, 2.5), "bathroom": (2.5, 2.0),
        "study": (3.5, 3.0), "dining": (3.5, 3.0),
        "hallway": (3.0, 1.2), "balcony": (3.0, 1.5),
    }
    
    tx = 0  # x offset for room placement (separate rooms)
    
    for i, (ph, nm) in enumerate(zip(photo_paths, room_names)):
        sr = {}
        if vlm_analysis and i < len(vlm_analysis) and vlm_analysis[i]:
            sr = vlm_analysis[i]
        
        rt = sr.get("room_type", nm)
        dims = sr.get("estimated_dimensions", {})
        
        # Get dimensions from VLM or defaults
        dl, dw = defaults.get(rt, (4.0, 3.5))
        lm = dims.get("length_mm", int(dl * 1000))
        wm = dims.get("width_mm", int(dw * 1000))
        hm = dims.get("height_mm", 2800)
        
        # Create room
        rid = str(uuid.uuid4())[:8]
        lmm, wmm, hmm = int(lm), int(wm), int(hm)
        
        # Floor polygon
        x0, z0 = tx, 0
        floor_pts = [
            Point3D(x0, 0, z0),
            Point3D(x0 + lmm, 0, z0),
            Point3D(x0 + lmm, 0, z0 + wmm),
            Point3D(x0, 0, z0 + wmm),
        ]
        
        room = Room(id=rid, name=nm, type=rt, floor_points=floor_pts, ceiling_height_mm=hmm)
        
        # Create walls
        wall_data = [
            ("south", x0, z0, x0 + lmm, z0),
            ("east", x0 + lmm, z0, x0 + lmm, z0 + wmm),
            ("north", x0 + lmm, z0 + wmm, x0, z0 + wmm),
            ("west", x0, z0 + wmm, x0, z0),
        ]
        
        for wname, sx, sz, ex, ez in wall_data:
            wid = str(uuid.uuid4())[:8]
            wall = Wall(
                id=wid, start=Point3D(sx, 0, sz), end=Point3D(ex, 0, ez),
                height_mm=hmm, thickness_mm=120,
                room_id=rid,
            )
            
            # Add doors/windows from VLM analysis
            struct = sr.get("structural_elements", {})
            
            # Check if door is on this wall
            for door in struct.get("doors", []):
                if door.get("position", "") == wname:
                    wall.openings.append(Opening(
                        id=str(uuid.uuid4())[:8],
                        type=OpeningType.DOOR,
                        offset_mm=wall.length_mm / 2 - door.get("width_mm", 900) / 2,
                        width_mm=door.get("width_mm", 900),
                        height_mm=door.get("height_mm", 2100),
                        swing="right",
                    ))
            
            # Check if window is on this wall
            for win in struct.get("windows", []):
                if win.get("position", "") == wname:
                    wall.openings.append(Opening(
                        id=str(uuid.uuid4())[:8],
                        type=OpeningType.WINDOW,
                        offset_mm=wall.length_mm / 2 - win.get("width_mm", 1500) / 2,
                        width_mm=win.get("width_mm", 1500),
                        height_mm=win.get("height_mm", 1500),
                        sill_height_mm=win.get("sill_height_mm", 900),
                    ))
            
            room.wall_ids.append(wid)
            scene.walls[wid] = wall
        
        scene.rooms[rid] = room
        tx += lmm + 1000  # gap between rooms
    
    # Save if output path provided
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        scene_json = {
            "name": scene.name,
            "rooms": [],
            "walls": [],
            "doors": [],
            "windows": [],
        }
        for r in scene.rooms.values():
            scene_json["rooms"].append({
                "id": r.id, "name": r.name, "type": r.type,
                "length_mm": int(max(p.x for p in r.floor_points) - min(p.x for p in r.floor_points)),
                "width_mm": int(max(p.z for p in r.floor_points) - min(p.z for p in r.floor_points)),
                "height_mm": r.ceiling_height_mm,
            })
        for w in scene.walls.values():
            scene_json["walls"].append({
                "id": w.id, "start": [w.start.x, w.start.y, w.start.z],
                "end": [w.end.x, w.end.y, w.end.z],
                "height": w.height_mm, "thickness": w.thickness_mm, "room_id": w.room_id,
            })
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(scene_json, f, ensure_ascii=False, indent=2)
        print("[Image2Scene] Scene saved to %s" % output_path)
    
    return scene


def generate_scene_from_roomplan(roomplan_path, output_path=None):
    """Convenience: load Scene3D from Apple RoomPlan JSON."""
    from core.scene3d import Scene3D
    scene = Scene3D.from_roomplan(roomplan_path)
    if output_path:
        scene.save(output_path)
    return scene


print("image2scene v2 ready - VLM-driven photo-to-3D")

