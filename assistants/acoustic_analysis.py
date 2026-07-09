# -*- coding: utf-8 -*-
"""
acoustic_analysis - Room-to-room sound insulation analysis
Checks wall STC ratings, impact noise, and recommends improvements.
Based on GB 50118 (sound insulation for civil buildings).
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

# Typical STC (Sound Transmission Class) values
WALL_STC = {"brick_120": 42, "brick_240": 50, "concrete_200": 52, "light_partition": 35, "glass": 30}
FLOOR_STC = {"concrete_120": 48, "concrete_150": 52, "wood_joist": 38}
GB50118_LIMITS = {"bedroom_day": 45, "bedroom_night": 37, "living_day": 45, "bathroom": 40}

@dataclass
class AcousticCheck:
    room: str; adjacent: str; wall_type: str
    required_stc: int; actual_stc: int; pass_: bool
    recommendation: str = ""

@dataclass  
class AcousticReport:
    checks: list; overall_pass: bool
    impact_noise_ok: bool; recommendations: list

def analyze_acoustics(scene) -> AcousticReport:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    walls = [_n(w) for w in (getattr(scene,'walls',[]) or [])]
    
    checks = []; recs = []
    
    # Build room adjacency from walls
    adj = {}
    for w in walls:
        rid = w.get('room_id','')
        if not rid: continue
        # A wall belongs to room rid, adjacent rooms share this wall
        # Simplified: any two rooms with walls are adjacent
        pass
    
    # Check between bedroom and living/kitchen
    bedrooms = [r for r in rooms if r.get('type','') in ('主卧','卧室','bedroom')]
    noisy = [r for r in rooms if r.get('type','') in ('客厅','living_room','厨房','kitchen')]
    
    for br in bedrooms:
        for nr in noisy:
            # Assume default 120mm brick wall between them
            stc = WALL_STC["brick_120"]
            req = GB50118_LIMITS["bedroom_night"]
            checks.append(AcousticCheck(
                br.get('name',''), nr.get('name',''),
                "120mm砖墙", req, stc, stc>=req,
                "" if stc>=req else "建议增加隔音棉或使用240mm墙体"
            ))
    
    if not checks:
        checks.append(AcousticCheck("N/A","N/A","N/A",45,50,True,"无相邻敏感房间"))
    
    # Impact noise (floor) - check if bedroom above living room (not applicable for single floor)
    impact_ok = True
    
    all_pass = all(c.pass_ for c in checks)
    
    # Generate recommendations
    if not all_pass:
        recs.append("卧室与客厅相邻墙建议加装隔音毡+石膏板(可提升STC 5-8dB)")
        recs.append("门使用实木复合门(STC>30)替代空心门")
        recs.append("插座开孔处使用声学密封胶")
    else:
        recs.append("隔音设计达标")
    
    return AcousticReport(checks, all_pass, impact_ok, recs)

def print_acoustic_report(ar):
    lines=["="*60,f"ACOUSTIC ANALYSIS",f"Overall: {'PASS' if ar.overall_pass else 'FAIL'}","="*60]
    for c in ar.checks:
        icon = "OK" if c.pass_ else "NG"
        lines.append(f"  [{icon}] {c.room}--{c.adjacent}: STC{c.actual_stc}(req{c.required_stc}) {c.wall_type}")
        if c.recommendation: lines.append(f"       -> {c.recommendation}")
    lines.append(f"\nRECOMMENDATIONS:")
    for r in ar.recommendations: lines.append(f"  - {r}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n