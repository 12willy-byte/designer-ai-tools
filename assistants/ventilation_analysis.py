# -*- coding: utf-8 -*-
"""
ventilation_analysis - Natural cross-ventilation & indoor air quality
Checks window placement for cross-ventilation, estimates ACH (air changes per hour).
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass
class VentCheck:
    room: str; has_cross_vent: bool; window_count: int
    window_area_m2: float; floor_area_m2: float
    ach_estimate: float; mech_vent_needed: bool
    recommendation: str = ""

@dataclass
class VentReport:
    checks: list; cross_vent_rooms: int; total_rooms: int
    mechanical_vent_needed: list; recommendations: list

def analyze_ventilation(scene) -> VentReport:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    walls = [_n(w) for w in (getattr(scene,'walls',[]) or [])]
    windows = [_n(w) for w in (getattr(scene,'windows',[]) or [])]
    
    if not rooms or not windows:
        return VentReport([], 0, len(rooms), [], ["无窗户数据,无法分析通风"])
    
    checks = []; cross_count = 0; mech_needed = []; recs = []
    
    for r in rooms:
        rt = r.get('type',''); nm = r.get('name','')
        area = r.get('length_mm',0)*r.get('width_mm',0)/1e6
        if area <= 0: continue
        
        # Find windows in this room
        rwindows = []
        rid = r.get('id','')
        for win in windows:
            w_rid = win.get('room_id', win.get('room',''))
            if w_rid == rid or w_rid == nm:
                rwindows.append(win)
        
        wcount = len(rwindows)
        warea = sum(w.get('width_mm',0)*w.get('height_mm',0)/1e6 for w in rwindows)
        
        # Cross-ventilation: windows on opposite walls
        has_cross = False
        if wcount >= 2:
            # Simplified: assume opposite-facing windows provide cross-vent
            has_cross = True
        
        # ACH estimate: Natural ventilation ~ 2-5 ACH with windows
        # ACH = (window area * wind speed * 3600) / (room volume)
        wind_speed = 0.5  # m/s typical indoor breeze
        volume = area * (r.get('height_mm',2800)/1000)
        ach = (warea * wind_speed * 3600) / volume if volume > 0 else 0
        ach = min(ach, 8)  # Cap at 8 ACH
        
        needs_mech = ach < 1.0 or rt in ('卫生间','bathroom','厨房','kitchen')
        
        if needs_mech:
            mech_needed.append(nm)
        
        if has_cross: cross_count += 1
        
        rec = ""
        if ach < 0.5:
            rec = "严重不足——必须安装机械排风"
        elif ach < 1.0:
            rec = "不足——建议增加窗户或安装排气扇"
        elif needs_mech:
            rec = "功能空间——安装排气扇(卫生间100m3/h,厨房300m3/h)"
        
        checks.append(VentCheck(nm, has_cross, wcount, round(warea,2), round(area,1), round(ach,2), needs_mech, rec))
    
    if mech_needed:
        recs.append(f"需机械通风: {', '.join(mech_needed)}")
    if cross_count < len(rooms) * 0.5 and len(rooms) > 2:
        recs.append("不足50%房间有穿堂风——重新考虑窗户位置")
    if cross_count >= len(rooms) * 0.5:
        recs.append("通风设计良好")
    
    return VentReport(checks, cross_count, len(rooms), mech_needed, recs)

def print_ventilation(vr):
    lines=["="*60,f"VENTILATION: {vr.cross_vent_rooms}/{vr.total_rooms} cross-ventilated","="*60]
    for c in vr.checks:
        icon = "OK" if c.has_cross_vent else ("WARN" if not c.mech_vent_needed else "NG")
        lines.append(f"  [{icon}] {c.room}: ACH={c.ach_estimate} | {c.window_count} windows | {c.window_area_m2}m2")
        if c.recommendation: lines.append(f"       -> {c.recommendation}")
    if vr.recommendations:
        lines.append(f"\nSummary:")
        for r in vr.recommendations: lines.append(f"  {r}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n