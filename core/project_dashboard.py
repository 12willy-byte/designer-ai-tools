# -*- coding: utf-8 -*-
"""
project_dashboard - Unified project dashboard API
Generates a single JSON with ALL analysis results for frontend consumption.
"""
import json, os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.scene_utils import normalize as _n
def generate_dashboard(scene, **analyses) -> dict:
    """Generate unified dashboard JSON with all analysis results."""
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    walls = [_n(w) for w in (getattr(scene,'walls',[]) or [])]
    
    total_area = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms)
    
    dashboard = {
        "project": {
            "name": getattr(scene,'name','Project'),
            "date": datetime.now().isoformat()[:19],
            "total_area_m2": round(total_area,1),
            "rooms": len(rooms),
            "walls": len(walls),
        },
        "rooms": [{
            "name": r.get('name',''), "type": r.get('type',''),
            "length_m": round(r.get('length_mm',0)/1000,1),
            "width_m": round(r.get('width_mm',0)/1000,1),
            "area_m2": round(r.get('length_mm',0)*r.get('width_mm',0)/1e6,1),
            "height_m": round(r.get('height_mm',0)/1000,1),
        } for r in rooms],
        "scores": {},
        "analyses": {},
    }
    
    # Validation
    val = analyses.get('validation')
    if val:
        dashboard["scores"]["validation"] = val.score
        dashboard["analyses"]["validation"] = {
            "score": val.score, "passed": val.passed,
            "errors": len(val.errors), "warnings": len(val.warnings),
        }
    
    # Critique
    cr = analyses.get('critique')
    if cr:
        dashboard["scores"]["critique"] = cr.score
        dashboard["analyses"]["critique"] = {
            "score": cr.score, "summary": cr.summary,
            "items": [{"cat":i.cat,"sev":i.sev.value,"title":i.title,"detail":i.detail} for i in cr.items[:10]],
        }
    
    # Cost
    cost = analyses.get('cost')
    if cost:
        s = cost.get('summary',{})
        dashboard["analyses"]["cost"] = {
            "grand_total": s.get('grand_total',0),
            "per_sqm": s.get('per_sqm',0),
            "breakdown": {k: v['total'] for k,v in cost.get('breakdown',{}).items()},
        }
    
    # Electrical
    e = analyses.get('electrical')
    if e:
        dashboard["analyses"]["electrical"] = {
            "points": len(e.points), "load_w": e.total_load_w,
            "main_breaker_a": e.main_breaker_a,
        }
    
    # MEP
    mep = analyses.get('mep')
    if mep:
        dashboard["analyses"]["mep"] = {
            "plumbing_points": len(mep.plumbing),
            "hvac_zones": len(mep.hvac),
            "ac_capacity_kw": mep.total_ac_capacity_kw,
        }
    
    # Daylight
    dl = analyses.get('daylight')
    if dl:
        dashboard["analyses"]["daylight"] = [{
            "room": d.room_name, "score": d.natural_light_score,
            "orientation": d.orientation, "meets_standard": d.meets_standard,
        } for d in dl]
    
    # Energy
    en = analyses.get('energy')
    if en:
        dashboard["analyses"]["energy"] = {
            "wall_u": en.wall_u_value, "roof_u": en.roof_u_value,
            "heating_kw": en.heating_load_kw, "cooling_kw": en.cooling_load_kw,
        }
    
    # Fire
    fr = analyses.get('fire')
    if fr:
        dashboard["analyses"]["fire"] = {
            "pass": fr.pass_count, "fail": fr.fail_count,
            "equipment": len(fr.equipment_needed),
        }
    
    # Accessibility
    acc = analyses.get('accessibility')
    if acc:
        dashboard["scores"]["accessibility"] = acc.score
    
    # Feng Shui
    fs = analyses.get('fengshui')
    if fs:
        dashboard["analyses"]["fengshui"] = {
            "good": fs.good_count, "bad": fs.bad_count,
            "overall": fs.overall,
        }
    
    # Acoustic
    ac = analyses.get('acoustic')
    if ac:
        dashboard["analyses"]["acoustic"] = {"pass": ac.overall_pass}
    
    # Schedule
    sch = analyses.get('schedule')
    if sch:
        dashboard["analyses"]["schedule"] = {
            "total_days": sch.total_days,
            "critical_tasks": len(sch.critical_path),
            "total_cost": sch.total_cost,
        }
    
    # Smart Home
    sh = analyses.get('smart_home')
    if sh:
        dashboard["analyses"]["smart_home"] = {
            "devices": sh.total_devices, "cost": sh.estimated_cost,
        }
    
    # Waste
    wr = analyses.get('waste')
    if wr:
        dashboard["analyses"]["waste"] = {
            "total_kg": wr.total_weight_kg, "recycling_rate": wr.recycling_rate,
        }
    
    # Ventilation
    vr = analyses.get('ventilation')
    if vr:
        dashboard["analyses"]["ventilation"] = {
            "cross_vent_rooms": vr.cross_vent_rooms,
            "total_rooms": vr.total_rooms,
        }
    
    # Adjacency
    ar = analyses.get('adjacency')
    if ar:
        dashboard["analyses"]["adjacency"] = {
            "total_affinity": ar.total_affinity,
            "max_possible": ar.max_possible,
        }
    
    # Layout
    lc = analyses.get('layout_count', 0)
    if lc:
        dashboard["analyses"]["furniture"] = {"pieces": lc}
    
    # Overall score
    scores = [v for v in dashboard["scores"].values() if isinstance(v,(int,float))]
    if scores:
        dashboard["scores"]["overall"] = round(sum(scores)/len(scores))
    
    return dashboard

def save_dashboard(dashboard, output_path="output/dashboard.json"):
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2, default=str)
    return output_path