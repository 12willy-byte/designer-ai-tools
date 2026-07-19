# -*- coding: utf-8 -*-
"""
daylight_analysis - Natural lighting & daylight analysis
Calculates window-to-floor ratio, solar exposure, and lighting recommendations per room.
Based on GB 50033 (Chinese daylighting standard) and international standards.
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene_utils import normalize as _n, get_rooms, get_walls, get_doors, get_windows
from dataclasses import dataclass, field

# GB 50033 minimum window-to-floor ratios by room type
GB50033_MIN_RATIOS = {
    "客厅": 0.143, "living_room": 0.143,
    "卧室": 0.143, "bedroom": 0.143, "主卧": 0.143,
    "厨房": 0.167, "kitchen": 0.167,
    "卫生间": 0.100, "bathroom": 0.100,
    "餐厅": 0.100, "dining": 0.100,
    "书房": 0.143, "study": 0.143,
    "走廊": 0.050, "hallway": 0.050,
}

@dataclass
class DaylightResult:
    room_name: str
    room_type: str
    floor_area_m2: float
    window_area_m2: float
    window_floor_ratio: float
    meets_standard: bool
    standard_min: float = 0.143
    natural_light_score: float = 0.0  # 0-100
    recommendations: list = field(default_factory=list)
    orientation: str = "unknown"
    sunlight_hours: float = 0.0

@dataclass
class LightingPlan:
    room_name: str
    ambient_lights: list
    task_lights: list
    accent_lights: list
    total_wattage: float = 0
    color_temp_k: int = 3000

def analyze_daylight(scene) -> list:
    """
    Analyze daylight for all rooms in Scene3D.
    
    Args:
        scene: Scene3D object or dict
    
    Returns:
        List of DaylightResult
    """
    results = []
    
    rooms = scene.get("rooms", []) if isinstance(scene, dict) else get_rooms(scene)
    walls = scene.get("walls", []) if isinstance(scene, dict) else get_walls(scene)
    windows = scene.get("windows", []) if isinstance(scene, dict) else get_windows(scene)
    doors = scene.get("doors", []) if isinstance(scene, dict) else get_doors(scene)
    
    # Build room->walls mapping
    room_wall_map = {}
    for w in walls:
        rid = w.get("room_id", "") if isinstance(w, dict) else getattr(w, 'room_id', '')
        if rid:
            room_wall_map.setdefault(rid, []).append(w)
    
    for room in rooms:
        rdata = room if isinstance(room, dict) else room.__dict__ if hasattr(room, '__dict__') else {}
        rname = rdata.get("name", "") if isinstance(rdata, dict) else getattr(room, 'name', '')
        rtype = rdata.get("type", "客厅") if isinstance(rdata, dict) else getattr(room, 'type', '客厅')
        
        # Calculate floor area
        length_mm = rdata.get("length_mm", 4000) if isinstance(rdata, dict) else getattr(room, 'length_mm', 4000)
        width_mm = rdata.get("width_mm", 3500) if isinstance(rdata, dict) else getattr(room, 'width_mm', 3500)
        floor_area = (length_mm * width_mm) / 1e6
        
        # Find windows in this room
        room_walls = room_wall_map.get(rdata.get("id", ""), [])
        total_window_area = 0
        window_orientation = "unknown"
        
        for w in room_walls:
            openings = w.get("openings", []) if isinstance(w, dict) else getattr(w, 'openings', [])
            for op in openings:
                if isinstance(op, dict) and op.get("type") == "window":
                    ww = op.get("width_mm", 0)
                    wh = op.get("height_mm", 0)
                    total_window_area += (ww * wh) / 1e6
                elif hasattr(op, 'type') and getattr(op, 'type', '') == "window":
                    ww = getattr(op, 'width_mm', 0)
                    wh = getattr(op, 'height_mm', 0)
                    total_window_area += (ww * wh) / 1e6
            
            # Estimate orientation from wall direction
            if isinstance(w, dict):
                sx, sz = w["start"][0], w["start"][2]
                ex, ez = w["end"][0], w["end"][2]
            else:
                sx, sz = w.start.x, w.start.z
                ex, ez = w.end.x, w.end.z
            
            dx, dz = ex - sx, ez - sz
            angle = math.degrees(math.atan2(dz, dx))
            if -45 <= angle < 45: window_orientation = "south"
            elif 45 <= angle < 135: window_orientation = "east" if dx < 0 else "west"
            elif -135 <= angle < -45: window_orientation = "west" if dx < 0 else "east"
            else: window_orientation = "north"
        
        # Calculate ratio
        wfr = total_window_area / floor_area if floor_area > 0 else 0
        standard_min = GB50033_MIN_RATIOS.get(rtype, 0.143)
        meets = wfr >= standard_min
        
        # Natural light score (0-100)
        base_score = min(wfr / standard_min * 60, 60)
        orientation_bonus = {"south": 30, "east": 20, "west": 20, "north": 5, "unknown": 10}.get(window_orientation, 10)
        score = min(base_score + orientation_bonus, 100)
        
        # Sunlight hours estimate
        sunlight = {"south": 6, "east": 3, "west": 4, "north": 1, "unknown": 2}.get(window_orientation, 2)
        
        # Recommendations
        recs = []
        if wfr < standard_min * 0.5:
            recs.append(f"CRITICAL: Window area too small ({wfr:.1%} vs {standard_min:.1%} required)")
            recs.append("  Consider: enlarge window, add skylight, or use light tubes")
        elif wfr < standard_min:
            recs.append(f"Insufficient daylight: {wfr:.1%} < {standard_min:.1%}")
            recs.append("  Supplement: add recessed LED downlights")
        
        if window_orientation == "north":
            recs.append("North-facing: low natural light. Use warm 3000K lighting")
            recs.append("  Consider light-colored walls to maximize reflection")
        elif window_orientation == "west":
            recs.append("West-facing: strong afternoon sun. Consider UV blinds")
        
        if total_window_area == 0:
            recs.append("No windows detected! Mechanical ventilation + full artificial lighting required")
        
        result = DaylightResult(
            room_name=rname, room_type=rtype,
            floor_area_m2=round(floor_area, 2),
            window_area_m2=round(total_window_area, 2),
            window_floor_ratio=round(wfr, 3),
            meets_standard=meets,
            standard_min=standard_min,
            natural_light_score=round(score, 1),
            recommendations=recs,
            orientation=window_orientation,
            sunlight_hours=sunlight,
        )
        results.append(result)
    
    return results

def generate_lighting_plan(daylight_results, scene=None) -> list:
    """
    Generate artificial lighting plan based on daylight analysis.
    
    Returns:
        List of LightingPlan per room
    """
    plans = []
    
    wattage_per_sqm = {
        "客厅": 4, "living_room": 4,
        "卧室": 3, "bedroom": 3,
        "厨房": 6, "kitchen": 6,
        "卫生间": 5, "bathroom": 5,
        "餐厅": 5, "dining": 5,
        "书房": 6, "study": 6,
    }
    
    for dr in daylight_results:
        area = dr.floor_area_m2
        watt_per_sqm = wattage_per_sqm.get(dr.room_type, 4)
        
        # Adjust for natural light
        if dr.natural_light_score > 70:
            watt_per_sqm *= 0.7
        elif dr.natural_light_score < 30:
            watt_per_sqm *= 1.3
        
        total_watt = area * watt_per_sqm
        
        # Color temperature by room function
        color_temp = {
            "客厅": 3000, "卧室": 2700, "厨房": 4000,
            "卫生间": 4000, "餐厅": 3000, "书房": 4000,
        }.get(dr.room_type, 3000)
        
        # Generate fixture plan
        ambient = []
        if area < 10:
            ambient.append({"type": "ceiling_light", "count": 1, "wattage": int(total_watt * 0.6)})
        elif area < 25:
            ambient.append({"type": "recessed_downlight", "count": max(4, int(area / 4)), "wattage": 7})
        else:
            ambient.append({"type": "recessed_downlight", "count": max(6, int(area / 3)), "wattage": 7})
            ambient.append({"type": "track_light", "count": max(1, int(area / 12)), "wattage": 15})
        
        task_lights = []
        if dr.room_type in ("厨房", "kitchen"):
            task_lights.append({"type": "under_cabinet", "count": 2, "wattage": 5})
        if dr.room_type in ("书房", "study"):
            task_lights.append({"type": "desk_lamp", "count": 1, "wattage": 8})
        if dr.room_type in ("卫生间", "bathroom"):
            task_lights.append({"type": "mirror_light", "count": 1, "wattage": 10})
        
        accent = []
        if dr.room_type in ("客厅", "living_room"):
            accent.append({"type": "wall_sconce", "count": 2, "wattage": 5})
        if dr.room_type in ("卧室", "bedroom"):
            accent.append({"type": "bedside_lamp", "count": 2, "wattage": 5})
        
        plans.append(LightingPlan(
            room_name=dr.room_name,
            ambient_lights=ambient,
            task_lights=task_lights,
            accent_lights=accent,
            total_wattage=round(total_watt, 1),
            color_temp_k=color_temp,
        ))
    
    return plans

def daylight_report(daylight_results, lighting_plans, output_path=None):
    """Generate comprehensive daylight + lighting report."""
    lines = ["=" * 60, "DAYLIGHT & LIGHTING ANALYSIS REPORT", "=" * 60, ""]
    
    for dr, lp in zip(daylight_results, lighting_plans):
        status = "PASS" if dr.meets_standard else "FAIL"
        lines.extend([
            f"--- {dr.room_name} ({dr.room_type}) ---",
            f"  Floor Area: {dr.floor_area_m2} m2",
            f"  Window Area: {dr.window_area_m2} m2",
            f"  Window/Floor Ratio: {dr.window_floor_ratio:.1%} (min: {dr.standard_min:.1%}) [{status}]",
            f"  Natural Light Score: {dr.natural_light_score}/100",
            f"  Orientation: {dr.orientation}, Est. Sunlight: {dr.sunlight_hours}h/day",
            f"  Artificial Lighting: {lp.total_wattage}W @ {lp.color_temp_k}K",
        ])
        
        if dr.recommendations:
            lines.append("  Recommendations:")
            for r in dr.recommendations:
                lines.append(f"    - {r}")
        
        amb_count = sum(a["count"] for a in lp.ambient_lights)
        task_count = sum(t["count"] for t in lp.task_lights)
        accent_count = sum(a["count"] for a in lp.accent_lights)
        lines.append(f"  Fixtures: {amb_count} ambient + {task_count} task + {accent_count} accent")
        lines.append("")
    
    report = "\n".join(lines)
    
    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
    
    return report

def auto_adjust_windows(scene, daylight_results):
    """
    Suggest window size adjustments to meet daylight standards.
    Returns list of adjustment suggestions.
    """
    adjustments = []
    
    for dr in daylight_results:
        if dr.meets_standard: continue
        needed_ratio = dr.standard_min
        current_area = dr.window_area_m2
        floor_area = dr.floor_area_m2
        needed_area = floor_area * needed_ratio
        deficit = needed_area - current_area
        
        if deficit > 0:
            adjustments.append({
                "room": dr.room_name,
                "current_window_m2": round(current_area, 2),
                "needed_window_m2": round(needed_area, 2),
                "deficit_m2": round(deficit, 2),
                "suggestion": f"Increase window by {deficit*10000:.0f} cm2 or add secondary window",
                "alternative": "Use light tube or solar tunnel if structural wall",
            })
    
    return adjustments