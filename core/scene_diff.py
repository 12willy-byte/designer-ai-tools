# -*- coding: utf-8 -*-
"""
scene_diff - Scene3D version comparison & revision tracking
Compares two Scene3D snapshots and generates a human-readable change report.
"""
import json, os, math, sys, hashlib, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field
from enum import Enum
def _norm(obj):
    """Normalize any object to a dict."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, '__dict__'):
        d = {}
        for k, v in obj.__dict__.items():
            if not k.startswith('_'):
                d[k] = v
        return d
    return {}

class ChangeType(Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    MOVED = "moved"
    RESIZED = "resized"
    UNCHANGED = "unchanged"

@dataclass
class Change:
    type: ChangeType
    entity: str
    entity_id: str
    field: str = ""
    old_value: str = ""
    new_value: str = ""
    detail: str = ""

@dataclass 
class DiffReport:
    version_old: str
    version_new: str
    timestamp: str
    total_changes: int
    changes: list = field(default_factory=list)
    summary: str = ""

from core.scene_utils import normalize as _n
def _hash_dict(d):
    return hashlib.md5(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:8]

def _delta(a, b):
    """Calculate numeric delta"""
    try:
        return round(float(b or 0) - float(a or 0), 2)
    except: return 0

def diff_scenes(scene_old, scene_new) -> DiffReport:
    """Compare two Scene3D objects and generate diff report."""
    changes = []
    
    ver_old = getattr(scene_old, 'name', 'v1') or 'v1'
    ver_new = getattr(scene_new, 'name', 'v2') or 'v2'
    
    # ---- Rooms ----
    old_rooms = {_norm(r).get('id',''): _norm(r) for r in (getattr(scene_old,'rooms',[]) or [])}
    new_rooms = {_norm(r).get('id',''): _norm(r) for r in (getattr(scene_new,'rooms',[]) or [])}
    
    old_ids = set(old_rooms.keys())
    new_ids = set(new_rooms.keys())
    
    for rid in new_ids - old_ids:
        r = new_rooms[rid]
        changes.append(Change(ChangeType.ADDED, "房间", rid, detail=f"新增房间: {r.get('name','')} ({r.get('length_mm',0)/1000:.1f}x{r.get('width_mm',0)/1000:.1f}m)"))
    
    for rid in old_ids - new_ids:
        r = old_rooms[rid]
        changes.append(Change(ChangeType.REMOVED, "房间", rid, detail=f"删除房间: {r.get('name','')}"))
    
    for rid in old_ids & new_ids:
        o, n = old_rooms[rid], new_rooms[rid]
        if o.get('name') != n.get('name'):
            changes.append(Change(ChangeType.MODIFIED, "房间", rid, "name", o.get('name',''), n.get('name',''), f"房间改名: {o.get('name','')} → {n.get('name','')}"))
        for dim in ['length_mm', 'width_mm', 'height_mm']:
            if abs(_delta(o.get(dim), n.get(dim))) > 10:
                changes.append(Change(ChangeType.RESIZED, "房间", rid, dim, str(o.get(dim,'')), str(n.get(dim,'')),
                    f"房间 {n.get('name','')} {dim}: {o.get(dim,0)/1000:.1f} → {n.get(dim,0)/1000:.1f}m"))
    
    # ---- Walls ----
    old_walls = {_norm(w).get('id',''): _norm(w) for w in (getattr(scene_old,'walls',[]) or [])}
    new_walls = {_norm(w).get('id',''): _norm(w) for w in (getattr(scene_new,'walls',[]) or [])}
    
    old_wids = set(old_walls.keys())
    new_wids = set(new_walls.keys())
    
    for wid in new_wids - old_wids:
        changes.append(Change(ChangeType.ADDED, "墙体", wid, detail="新增墙体"))
    
    for wid in old_wids - new_wids:
        changes.append(Change(ChangeType.REMOVED, "墙体", wid, detail="删除墙体"))
    
    for wid in old_wids & new_wids:
        o, n = old_walls[wid], new_walls[wid]
        o_len = o.get('length_mm', 0) or math.hypot(o['end'][0]-o['start'][0], o['end'][2]-o['start'][2]) if 'end' in o else 0
        n_len = n.get('length_mm', 0) or math.hypot(n['end'][0]-n['start'][0], n['end'][2]-n['start'][2]) if 'end' in n else 0
        if abs(o_len - n_len) > 50:
            changes.append(Change(ChangeType.RESIZED, "墙体", wid, "length_mm", f"{o_len:.0f}", f"{n_len:.0f}", f"墙体长度: {o_len/1000:.1f} → {n_len/1000:.1f}m"))
        
        # Check openings changes
        o_ops = o.get('openings', [])
        n_ops = n.get('openings', [])
        if len(o_ops) != len(n_ops):
            changes.append(Change(ChangeType.MODIFIED, "墙体开口", wid, detail=f"开口数量: {len(o_ops)} → {len(n_ops)}"))
    
    # ---- Furniture ----
    old_furn = {_norm(f).get('id',''): _norm(f) for f in (getattr(scene_old,'furniture',[]) or [])}
    new_furn = {_norm(f).get('id',''): _norm(f) for f in (getattr(scene_new,'furniture',[]) or [])}
    
    old_fids = set(old_furn.keys())
    new_fids = set(new_furn.keys())
    
    for fid in new_fids - old_fids:
        f = new_furn[fid]
        changes.append(Change(ChangeType.ADDED, "家具", fid, detail=f"新增: {f.get('name','')}"))
    
    for fid in old_fids - new_fids:
        f = old_furn[fid]
        changes.append(Change(ChangeType.REMOVED, "家具", fid, detail=f"移除: {f.get('name','')}"))
    
    for fid in old_fids & new_fids:
        o, n = old_furn[fid], new_furn[fid]
        op = o.get('position', [0,0,0]); np = n.get('position', [0,0,0])
        dist = math.hypot(np[0]-op[0], np[2]-op[2])
        if dist > 100:
            changes.append(Change(ChangeType.MOVED, "家具", fid, detail=f"{n.get('name','')} 移动了 {dist:.0f}mm"))
    
    # ---- Doors & Windows ----
    for entity in ['doors', 'windows']:
        old_set = {_norm(d).get('id',''): _norm(d) for d in (getattr(scene_old, entity, []) or [])}
        new_set = {_norm(d).get('id',''): _norm(d) for d in (getattr(scene_new, entity, []) or [])}
        
        for did in set(new_set.keys()) - set(old_set.keys()):
            changes.append(Change(ChangeType.ADDED, entity, did, detail=f"新增{entity}"))
        for did in set(old_set.keys()) - set(new_set.keys()):
            changes.append(Change(ChangeType.REMOVED, entity, did, detail=f"移除{entity}"))
    
    # ---- Summary ----
    added = sum(1 for c in changes if c.type == ChangeType.ADDED)
    removed = sum(1 for c in changes if c.type == ChangeType.REMOVED)
    modified = sum(1 for c in changes if c.type in (ChangeType.MODIFIED, ChangeType.MOVED, ChangeType.RESIZED))
    
    summary = f"{added} added, {removed} removed, {modified} modified"
    if not changes:
        summary = "No changes detected — scenes are identical"
    
    return DiffReport(
        version_old=ver_old,
        version_new=ver_new,
        timestamp=datetime.datetime.now().isoformat()[:19],
        total_changes=len(changes),
        changes=changes,
        summary=summary,
    )

def print_diff(report: DiffReport):
    """Pretty-print diff report."""
    lines = [
        "=" * 60,
        f"  SCENE DIFF: {report.version_old} → {report.version_new}",
        f"  {report.timestamp}",
        f"  Changes: {report.total_changes} ({report.summary})",
        "=" * 60,
    ]
    
    icons = {"added": "➕", "removed": "➖", "modified": "✏️", "moved": "↗️", "resized": "📐", "unchanged": "  "}
    
    for c in report.changes:
        icon = icons.get(c.type.value if hasattr(c.type,'value') else c.type, "  ")
        if c.detail:
            lines.append(f"  {icon} [{c.entity}] {c.detail}")
        else:
            lines.append(f"  {icon} [{c.entity}] {c.field}: {c.old_value} → {c.new_value}")
    
    if not report.changes:
        lines.append("  ✅ No changes")
    
    lines.append("=" * 60)
    text = "\n".join(lines)
    print(text)
    return text

def save_diff(report: DiffReport, output_path: str):
    """Save diff report as JSON."""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'version_old': report.version_old,
            'version_new': report.version_new,
            'timestamp': report.timestamp,
            'total_changes': report.total_changes,
            'summary': report.summary,
            'changes': [{'type': c.type.value, 'entity': c.entity, 'id': c.entity_id, 'detail': c.detail} for c in report.changes],
        }, f, ensure_ascii=False, indent=2)
    return output_path