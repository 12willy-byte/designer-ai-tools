# -*- coding: utf-8 -*-
"""validation_engine - Scene3D validation & auto-fix"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field
from enum import Enum

class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

@dataclass
class ValidationIssue:
    code: str
    severity: Severity
    category: str
    message: str
    location: str = ""
    suggestion: str = ""

@dataclass
class ValidationReport:
    scene_name: str
    total_checks: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    infos: list = field(default_factory=list)
    passed: bool = False
    score: float = 0.0

from core.scene_utils import normalize as _n, get_rooms, get_walls, get_doors, get_windows
_norm = _n  # alias for modules that use _norm
def _coord(p, axis=0):
    """Get coordinate from list/tuple/dict/Point3D"""
    if isinstance(p, (list, tuple)): return p[axis]
    if isinstance(p, dict): return p.get(('x','y','z')[axis], 0)
    if hasattr(p, ('x','y','z')[axis]): return getattr(p, ('x','y','z')[axis])
    return 0

def _wlen(w):
    """Wall length from any format"""
    d = _norm(w)
    if d.get('length_mm'): return d['length_mm']
    s, e = d.get('start',[0,0,0]), d.get('end',[0,0,0])
    return math.hypot(_coord(e,0)-_coord(s,0), _coord(e,2)-_coord(s,2))

def validate_scene(scene):
    """Comprehensive Scene3D validation"""
    report = ValidationReport(scene_name=getattr(scene,'name','unknown'))
    rooms = [(_norm(r), r) for r in (getattr(scene,'rooms',[]) or [])]
    walls = [(_norm(w), w) for w in (getattr(scene,'walls',[]) or [])]
    doors = [(_norm(d), d) for d in (getattr(scene,'doors',[]) or [])]
    windows = [(_norm(w), w) for w in (getattr(scene,'windows',[]) or [])]
    furniture = [(_norm(f), f) for f in (getattr(scene,'furniture',[]) or [])]
    
    checks = []
    def add(code, sev, cat, msg, cond, sug=""):
        if cond: checks.append(ValidationIssue(code=code,severity=sev,category=cat,message=msg,suggestion=sug))
    
    add("C001", Severity.ERROR, "Data", "No rooms found", not rooms, "Import from RoomPlan or CAD")
    add("C002", Severity.ERROR, "Data", "No walls found", not walls, "Import from RoomPlan or CAD")
    add("C001", Severity.INFO, "Data", f"{len(rooms)} rooms found", bool(rooms))
    add("C002", Severity.INFO, "Data", f"{len(walls)} walls found", bool(walls))
    
    wall_ids = set()
    for wd, w in walls:
        wid = wd.get('id','')
        if wid and wid in wall_ids:
            add("G001", Severity.ERROR, "Geometry", f"Duplicate wall ID: {wid}", True, "Use unique IDs")
        if wid: wall_ids.add(wid)
        L = _wlen(wd)
        if 0 < L < 100: add("G002", Severity.WARNING, "Geometry", f"Wall {wid} too short ({L:.0f}mm)", True)
        if L > 20000: add("G003", Severity.WARNING, "Geometry", f"Wall {wid} very long ({L:.0f}mm)", True)
    
    room_ids = set()
    for rd, r in rooms:
        rid = rd.get('id','')
        if rid and rid in room_ids: add("R001", Severity.ERROR, "Room", f"Duplicate room ID: {rid}", True)
        if rid: room_ids.add(rid)
        area = rd.get('length_mm',0) * rd.get('width_mm',0) / 1e6
        if 0 < area < 3: add("R002", Severity.WARNING, "Room", f"Room {rid} too small ({area:.1f}m2)", area < 3)
        if area > 100: add("R003", Severity.INFO, "Room", f"Room {rid} is large ({area:.1f}m2)", area > 100)
    
    for dd, d in doors:
        dw = dd.get('width_mm', 0) or 900
        if 0 < dw < 600: add("D001", Severity.ERROR, "Door", f"Door width {dw}mm < 600mm", True, "Min 600mm")
        elif dw < 800: add("D002", Severity.WARNING, "Door", f"Door width {dw}mm < 800mm", True, "Recommend >= 800mm")
    
    for wd2, win in windows:
        wa = wd2.get('width_mm',0) * wd2.get('height_mm',0) / 1e6
        if 0 < wa < 0.3: add("W001", Severity.WARNING, "Window", f"Window area {wa:.2f}m2 too small", True)
    
    total_floor = sum(rd.get('length_mm',0)*rd.get('width_mm',0)/1e6 for rd,_ in rooms)
    add("DR01", Severity.INFO, "Design", f"Total area: {total_floor:.1f}m2", total_floor > 0)
    
    has_corridor = any(rd.get('type','') in ('走廊','hallway','玄关') for rd,_ in rooms)
    if not has_corridor and len(rooms) > 3:
        add("DR02", Severity.WARNING, "Design", "No corridor detected in multi-room layout", True)
    
    # Furniture clearance
    for i in range(len(furniture)):
        for j in range(i+1, len(furniture)):
            p1 = furniture[i][0].get('position', [0,0,0])
            p2 = furniture[j][0].get('position', [0,0,0])
            dist = math.hypot(p1[0]-p2[0], p1[2]-p2[2])
            if dist < 100:
                add("F001", Severity.WARNING, "Furniture", f"Furniture too close ({dist:.0f}mm)", True)
    
    report.errors = [c for c in checks if c.severity == Severity.ERROR]
    report.warnings = [c for c in checks if c.severity == Severity.WARNING]
    report.infos = [c for c in checks if c.severity == Severity.INFO]
    report.total_checks = len(checks)
    
    max_score = max(len(checks)*10, 1)
    penalty = sum(10 for c in report.errors) + sum(3 for c in report.warnings)
    report.score = max(0, min(100, (max_score - penalty) / max_score * 100))
    report.passed = len(report.errors) == 0
    return report

def print_validation_report(report):
    lines = ["="*60, f"VALIDATION: {report.scene_name}", f"Score: {report.score:.0f}/100 | Passed: {'YES' if report.passed else 'NO'}",
             f"Errors: {len(report.errors)} | Warnings: {len(report.warnings)} | Info: {len(report.infos)}", "="*60]
    for i in report.errors:
        lines.append(f"  [ERROR] [{i.code}] {i.message}")
        if i.suggestion: lines.append(f"          -> {i.suggestion}")
    for i in report.warnings:
        lines.append(f"  [WARN]  [{i.code}] {i.message}")
        if i.suggestion: lines.append(f"          -> {i.suggestion}")
    for i in report.infos:
        lines.append(f"  [INFO]  [{i.code}] {i.message}")
    if not report.errors and not report.warnings: lines.append("  All good!")
    lines.append("="*60)
    s = "\n".join(lines)
    print(s)
    return s

def auto_fix_common_issues(scene):
    fixes = []
    walls = get_walls(scene)
    rooms = get_rooms(scene)
    for w in walls:
        wd = _norm(w)
        if not wd.get('room_id'):
            cx = (_coord(wd.get('start',[0,0,0]),0)+_coord(wd.get('end',[0,0,0]),0))/2
            cz = (_coord(wd.get('start',[0,0,0]),2)+_coord(wd.get('end',[0,0,0]),2))/2
            best, best_dist = None, float('inf')
            for r in rooms:
                rd = _norm(r)
                rx = _coord(rd.get('position',[0,0,0]),0)
                rz = _coord(rd.get('position',[0,0,0]),2)
                d = math.hypot(cx-rx, cz-rz)
                if d < best_dist: best, best_dist = r, d
            if best and best_dist < 5000:
                if hasattr(w, 'room_id'): w.room_id = best.id if hasattr(best,'id') else _norm(best).get('id','')
                elif isinstance(w, dict): w['room_id'] = best.get('id','') if isinstance(best,dict) else _norm(best).get('id','')
                fixes.append(f"Assigned wall to room")
    return scene, fixes