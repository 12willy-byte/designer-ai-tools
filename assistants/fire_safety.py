# -*- coding: utf-8 -*-
"""
fire_safety - Fire safety compliance check
Escape routes, smoke detectors, fire extinguishers, sprinkler zones.
Based on GB 50016 (fire protection for building design).
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass
class FireCheck:
    id: str; category: str; status: str  # pass/fail/warn
    detail: str; regulation: str; fix: str = ""

@dataclass
class FireReport:
    checks: list; pass_count: int; fail_count: int
    escape_plan: list; equipment_needed: list

def check_fire_safety(scene) -> FireReport:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    doors = [_n(d) for d in (getattr(scene,'doors',[]) or [])]
    walls = [_n(w) for w in (getattr(scene,'walls',[]) or [])]
    
    total = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms)
    n = len(rooms)
    checks = []; equip = []
    
    # 1. Escape route distance
    max_escape = 0
    for r in rooms:
        diag = math.hypot(r.get('length_mm',4000), r.get('width_mm',3500))/1000
        if diag > max_escape: max_escape = diag
    
    if max_escape > 15:
        checks.append(FireCheck("F01","逃生距离","fail",
            f"最远疏散距离{max_escape:.0f}m>15m","GB50016 5.5.17",
            "增设安全出口或缩短走廊"))
    else:
        checks.append(FireCheck("F01","逃生距离","pass",
            f"疏散距离{max_escape:.0f}m <= 15m","GB50016 5.5.17"))
    
    # 2. Smoke detector count
    det_count = max(1, int(total/40))
    equip.append({"type":"烟感探测器","count":det_count,"location":"每个房间+走廊","note":"GB50116"})
    checks.append(FireCheck("F02","烟感","pass",
        f"需要{det_count}个烟感(按{total:.0f}m2)","GB50116"))
    
    # 3. Fire extinguisher
    ext_count = max(1, int(total/50))
    equip.append({"type":"灭火器 2kg ABC干粉","count":ext_count,"location":"厨房+走廊","note":"GB50140"})
    
    # 4. Emergency lighting
    equip.append({"type":"应急照明灯","count":max(2,int(n/3)),"location":"走廊+出口","note":"GB17945"})
    equip.append({"type":"疏散指示标志","count":max(1,int(n/4)),"location":"出口上方","note":"GB17945"})
    
    # 5. Gas leak detector (if kitchen)
    has_kitchen = any(r.get('type','') in ('厨房','kitchen') for r in rooms)
    if has_kitchen:
        equip.append({"type":"燃气泄漏报警器","count":1,"location":"厨房","note":"CJJ12"})
        checks.append(FireCheck("F03","燃气","pass","厨房需安装燃气报警器","CJJ12"))
    
    # 6. Door width for escape
    narrow_doors = [d for d in doors if 0 < d.get('width_mm',0) < 800]
    if narrow_doors:
        checks.append(FireCheck("F04","疏散门宽","fail",
            f"{len(narrow_doors)}扇门<800mm","GB50016 5.5.18",
            "疏散门净宽>=800mm"))
    else:
        checks.append(FireCheck("F04","疏散门宽","pass","门宽>=800mm","GB50016 5.5.18"))
    
    pass_c = sum(1 for c in checks if c.status=='pass')
    fail_c = sum(1 for c in checks if c.status=='fail')
    
    return FireReport(checks, pass_c, fail_c, 
        [f"疏散路线: 各房间->走廊->入户门 (最远{max_escape:.0f}m)"],
        equip)

def print_fire_report(fr):
    lines=["="*60,f"FIRE SAFETY: {fr.pass_count}P/{fr.fail_count}F/{len(fr.checks)}","="*60]
    for c in fr.checks:
        icon = "OK" if c.status=="pass" else "NG"
        lines.append(f"  [{icon}] [{c.category}] {c.detail}")
        lines.append(f"       GB: {c.regulation}")
        if c.fix: lines.append(f"       -> {c.fix}")
    lines.append(f"\nEQUIPMENT NEEDED:")
    for e in fr.equipment_needed:
        lines.append(f"  - {e['type']} x{e['count']} @{e['location']}")
    if fr.escape_plan:
        lines.append(f"\nESCAPE PLAN:")
        for ep in fr.escape_plan: lines.append(f"  {ep}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n