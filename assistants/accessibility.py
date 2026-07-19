# -*- coding: utf-8 -*-
"""
accessibility - Accessibility & universal design check
Wheelchair clearances, grab bars, threshold heights, door widths.
Based on GB 50763 (accessibility design code).
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass  
class AccCheck:
    id: str; category: str; status: str; detail: str; fix: str = ""

@dataclass
class AccReport:
    checks: list; score: int; recommendations: list

def check_accessibility(scene) -> AccReport:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    doors = [_n(d) for d in (getattr(scene,'doors',[]) or [])]
    checks = []
    
    # 1. Entry door width >= 900mm for wheelchair
    entry_doors = [d for d in doors if d.get('width_mm',0) > 0]
    narrow = [d for d in entry_doors if d.get('width_mm',0) < 800]
    if narrow:
        checks.append(AccCheck("A01","入户门","fail",
            f"{len(narrow)}扇门<800mm,轮椅需>=800mm",
            "入户门>=900mm,室内门>=800mm"))
    else:
        checks.append(AccCheck("A01","入户门","pass","门宽>=800mm"))
    
    # 2. Corridor width >= 1200mm
    corridors = [r for r in rooms if r.get('type','') in ('走廊','hallway','玄关')]
    narrow_corr = [r for r in corridors if r.get('width_mm',0) < 1200 and r.get('width_mm',0) > 0]
    if narrow_corr:
        checks.append(AccCheck("A02","走廊宽度","fail",
            f"走廊<1200mm,轮椅回转需>=1500mm",
            "走廊>=1200mm,转弯处>=1500mm"))
    elif corridors:
        checks.append(AccCheck("A02","走廊宽度","pass","走廊宽度>=1200mm"))
    
    # 3. Bathroom accessibility
    bathrooms = [r for r in rooms if r.get('type','') in ('卫生间','bathroom')]
    for br in bathrooms:
        area = br.get('length_mm',0)*br.get('width_mm',0)/1e6
        if 0 < area < 3.5:
            checks.append(AccCheck("A03","卫生间","warn",
                f"面积{area:.1f}m2<3.5m2,轮椅回转困难",
                "无障碍卫生间>=3.5m2,设L型扶手"))
        elif area >= 3.5:
            checks.append(AccCheck("A03","卫生间","pass",f"面积{area:.1f}m2>=3.5m2"))
    
    # 4. Threshold
    checks.append(AccCheck("A04","门槛","warn",
        "确保门槛高度<=15mm或做斜坡处理","GB50763 入户门无门槛或<=15mm"))
    
    # 5. Switch/socket height
    checks.append(AccCheck("A05","开关高度","warn",
        "开关建议900-1100mm,插座>=400mm","GB50763 便于轮椅使用者"))
    
    score = 100 - sum(15 for c in checks if c.status=='fail') - sum(5 for c in checks if c.status=='warn')
    score = max(0, score)
    
    recs = []
    if score < 80:
        recs.append("卫生间加装L型扶手+折叠淋浴凳")
        recs.append("入户门改用无门槛设计或斜坡过渡")
        recs.append("走廊转角半径>=500mm")
    else:
        recs.append("基础无障碍达标,可进一步优化")
    
    return AccReport(checks, score, recs)

def print_acc_report(ar):
    lines=["="*60,f"ACCESSIBILITY: Score {ar.score}/100","="*60]
    for c in ar.checks:
        icon = "OK" if c.status=="pass" else ("WARN" if c.status=="warn" else "NG")
        lines.append(f"  [{icon}] [{c.category}] {c.detail}")
        if c.fix: lines.append(f"       -> {c.fix}")
    if ar.recommendations:
        lines.append(f"\nRECOMMENDATIONS:")
        for r in ar.recommendations: lines.append(f"  - {r}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n