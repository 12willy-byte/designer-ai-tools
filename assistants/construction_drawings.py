# -*- coding: utf-8 -*-
"""
construction_drawings - Construction drawing generation from Scene3D
Generates: furniture plan + ceiling plan + elevations + section details + axonometric
Output: SVG (vector) + optional PNG
"""
import json, os, math, uuid
from dataclasses import dataclass, field
import numpy as np

SCALE = 0.2

# === Coordinate helpers ===
def _xyz(p, axis=0):
    """Normalize coordinate access: list[x,y,z] | dict{x,y,z} | Point3D dataclass"""
    if isinstance(p, (list, tuple)): return p[axis]
    if isinstance(p, dict): return p.get(('x','y','z')[axis], 0)
    if hasattr(p, 'x'): return getattr(p, ('x','y','z')[axis], 0)
    return 0

def _ws(w, a=0): s = w.get('start',w) if isinstance(w,dict) else getattr(w,'start',w); return _xyz(s,a)
def _we(w, a=0): e = w.get('end',w) if isinstance(w,dict) else getattr(w,'end',w); return _xyz(e,a)
def _wh(w):
    if isinstance(w,dict): return w.get('height',w.get('height_mm',2800))
    if hasattr(w,'height_mm'): return w.height_mm
    if hasattr(w,'height'): return w.height
    return 2800
def _wlen(w):
    if isinstance(w,dict) and 'length_mm' in w: return w['length_mm']
    if hasattr(w,'length_mm'): return w.length_mm
    return math.hypot(_we(w,0)-_ws(w,0), _we(w,2)-_ws(w,2))

def mm_to_svg(v, o=0): return v * SCALE + o

SVG_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" width="{w}mm" height="{h}mm">\n<style>\n  .wall{{fill:#333;stroke:#000;stroke-width:0.5;}} .wall-thin{{fill:#999;}}\n  .door{{fill:#fff;stroke:#00f;stroke-width:0.3;}} .door-swing{{fill:none;stroke:#00f;stroke-width:0.2;stroke-dasharray:1,1;}}\n  .window{{fill:#cdf;stroke:#06f;stroke-width:0.3;}}\n  .dim{{stroke:#f00;stroke-width:0.15;fill:none;}} .dim-text{{fill:#f00;font-size:2.5px;text-anchor:middle;font-family:sans-serif;}}\n  .label{{fill:#000;font-size:3px;text-anchor:middle;font-family:sans-serif;}}\n  .grid{{stroke:#ddd;stroke-width:0.1;fill:none;}}\n  .furniture{{fill:#eee;stroke:#666;stroke-width:0.2;}} .hatch{{fill:url(#hatch);stroke:#333;stroke-width:0.3;}}\n  .beam{{fill:#c60;stroke:#840;stroke-width:0.3;}} .column{{fill:#666;stroke:#333;stroke-width:0.3;}}\n</style>\n<defs><pattern id="hatch" width="2" height="2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="2" stroke="#999" stroke-width="0.3"/></pattern></defs>\n'
SVG_FOOT = '</svg>'

# ============================================================
# 1. Furniture Layout Plan
# ============================================================

def generate_furniture_plan_svg(scene_dict, output_path=None):
    walls = scene_dict.get("walls", [])
    furniture = scene_dict.get("furniture", [])
    doors = scene_dict.get("doors", [])
    windows = scene_dict.get("windows", [])
    rooms = scene_dict.get("rooms", [])
    if not walls: return None
    
    xs, zs = [], []
    for w in walls:
        xs.extend([_ws(w,0), _we(w,0)])
        zs.extend([_ws(w,2), _we(w,2)])
    
    min_x, max_x, min_z, max_z = min(xs), max(xs), min(zs), max(zs)
    margin = 1000
    svg_w = (max_x - min_x + 2*margin)*SCALE
    svg_h = (max_z - min_z + 2*margin)*SCALE
    
    lines = [SVG_HEAD.format(x=0,y=0,w=svg_w,h=svg_h)]
    ox, oz = -min_x + margin, -min_z + margin
    
    # Grid
    for i in range(0, int(svg_w)+1, 100):
        lines.append(f'<line x1="{i}" y1="0" x2="{i}" y2="{svg_h}" class="grid"/>')
    for j in range(0, int(svg_h)+1, 100):
        lines.append(f'<line x1="0" y1="{j}" x2="{svg_w}" y2="{j}" class="grid"/>')
    
    # Walls
    for w in walls:
        sx, sz = mm_to_svg(_ws(w,0), ox), mm_to_svg(_ws(w,2), oz)
        ex, ez = mm_to_svg(_we(w,0), ox), mm_to_svg(_we(w,2), oz)
        t = w.get("thickness", 120)*SCALE/2 if isinstance(w,dict) else (getattr(w,'thickness_mm',120) if hasattr(w,'thickness_mm') else 120)*SCALE/2
        dx, dy = ex - sx, ez - sz
        length = math.hypot(dx, dy)
        if length < 0.01: continue
        nx, ny = -dy/length, dx/length
        pts = f"{sx+nx*t:.1f},{sz+ny*t:.1f} {ex+nx*t:.1f},{ez+ny*t:.1f} {ex-nx*t:.1f},{ez-ny*t:.1f} {sx-nx*t:.1f},{sz-ny*t:.1f}"
        cls = "wall" if (isinstance(w,dict) and w.get("is_load_bearing")) else "wall-thin"
        lines.append(f'<polygon points="{pts}" class="{cls}"/>')
    
    # Doors & Windows
    for d in doors + windows:
        wall_id = d.get("wall_id", d.get("wall", ""))
        offset = d.get("offset_mm", 0)
        width = d.get("width_mm", 900)
        wall = next((w for w in walls if (isinstance(w,dict) and w.get("id")==wall_id) or (hasattr(w,'id') and w.id==wall_id)), None)
        if not wall: continue
        
        swx, swz = _ws(wall,0), _ws(wall,2)
        ewx, ewz = _we(wall,0), _we(wall,2)
        wl = math.hypot(ewx-swx, ewz-swz)
        if wl < 0.01: continue
        
        dx, dz = (ewx-swx)/wl, (ewz-swz)/wl
        d_svg_x = mm_to_svg(swx + dx*offset, ox)
        d_svg_y = mm_to_svg(swz + dz*offset, oz)
        ew_svg = width * SCALE
        
        is_door = d.get("type","") in ("door","Door") or d.get("opening_type","") == "door"
        if is_door:
            lines.append(f'<rect x="{d_svg_x - ew_svg/2:.1f}" y="{d_svg_y - 1:.1f}" width="{ew_svg:.1f}" height="2" class="door"/>')
            lines.append(f'<path d="M {d_svg_x:.1f},{d_svg_y:.1f} Q {d_svg_x + ew_svg/2:.1f},{d_svg_y - 15:.1f} {d_svg_x + ew_svg:.1f},{d_svg_y:.1f}" class="door-swing"/>')
        else:
            lines.append(f'<rect x="{d_svg_x - ew_svg/2:.1f}" y="{d_svg_y - 0.5:.1f}" width="{ew_svg:.1f}" height="1" class="window"/>')
    
    # Furniture
    for f in furniture:
        pos = f.get("position", [0,0,0])
        fw = f.get("width_mm",500)*SCALE
        fd = f.get("depth_mm",500)*SCALE
        fx = mm_to_svg(_xyz(pos,0),ox) - fw/2
        fy = mm_to_svg(_xyz(pos,2),oz) - fd/2
        name = f.get("name","")[:4]
        lines.append(f'<rect x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fd:.1f}" class="furniture"/>')
        if name: lines.append(f'<text x="{fx+fw/2:.1f}" y="{fy+fd/2+1:.1f}" class="label" font-size="2px">{name}</text>')
    
    # Dimensions
    for i, w in enumerate(walls):
        if i%2: continue
        sx, sz = mm_to_svg(_ws(w,0),ox), mm_to_svg(_ws(w,2),oz)
        ex, ez = mm_to_svg(_we(w,0),ox), mm_to_svg(_we(w,2),oz)
        dx, dy = ex-sx, ez-sz
        length = math.hypot(dx,dy)
        if length < 5: continue
        nx, ny = -dy/length, dx/length
        dist = -15
        dim_sy, dim_ey = sz+ny*dist, ez+ny*dist
        lines.append(f'<line x1="{sx:.1f}" y1="{dim_sy:.1f}" x2="{ex:.1f}" y2="{dim_ey:.1f}" class="dim"/>')
        mid_x, mid_y = (sx+ex)/2, (dim_sy+dim_ey)/2
        wmm = int(_wlen(w))
        lines.append(f'<text x="{mid_x:.1f}" y="{mid_y-1:.1f}" class="dim-text">{wmm}</text>')
    
    # Room labels
    for room in rooms:
        rname = room.get("name","")
        if rname:
            pos = room.get("position", None)
            if pos: cx, cz = mm_to_svg(_xyz(pos,0),ox), mm_to_svg(_xyz(pos,2),oz)
            else: cx, cz = svg_w/2, svg_h/2
            lines.append(f'<text x="{cx:.1f}" y="{cz:.1f}" class="label" font-weight="bold">{rname}</text>')
    
    lines.append(SVG_FOOT)
    svg_content = "\n".join(lines)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f: f.write(svg_content)
    return svg_content

# ============================================================
# 2. Elevation View
# ============================================================

def generate_elevation_svg(scene_dict, wall_id=None, output_path=None):
    walls = scene_dict.get("walls", [])
    if not walls: return None
    
    target = walls[0]
    if wall_id:
        tgt = next((w for w in walls if (isinstance(w,dict) and w.get("id")==wall_id) or (hasattr(w,'id') and w.id==wall_id)), None)
        if tgt: target = tgt
    
    h = _wh(target)
    wl = _wlen(target)
    margin = 500
    
    svg_w = (wl + 2*margin)*SCALE
    svg_h = (h + 2*margin)*SCALE
    lines = [SVG_HEAD.format(x=0,y=0,w=svg_w,h=svg_h)]
    ox, oy = margin, margin
    
    wx, wy = mm_to_svg(0,ox), mm_to_svg(0,oy)
    ww, wh = wl*SCALE, h*SCALE
    
    lines.append(f'<rect x="{wx:.1f}" y="{wy:.1f}" width="{ww:.1f}" height="{wh:.1f}" fill="#f5f0e8" stroke="#333" stroke-width="0.5"/>')
    
    # Ground line
    ground_y = mm_to_svg(h, oy)
    lines.append(f'<line x1="{wx-5:.1f}" y1="{ground_y:.1f}" x2="{wx+ww+5:.1f}" y2="{ground_y:.1f}" stroke="#000" stroke-width="2"/>')
    
    # Openings
    for op in (target.get("openings",[]) if isinstance(target,dict) else getattr(target,'openings',[]) or []):
        off = op.get("offset_mm",0) if isinstance(op,dict) else getattr(op,'offset_mm',0)
        ow = op.get("width_mm",900) if isinstance(op,dict) else getattr(op,'width_mm',900)
        oh = op.get("height_mm",2100) if isinstance(op,dict) else getattr(op,'height_mm',2100)
        sh = op.get("sill_height_mm",0) if isinstance(op,dict) else getattr(op,'sill_height_mm',0)
        otype = op.get("type","door") if isinstance(op,dict) else getattr(op,'type','door')
        
        ox_svg = mm_to_svg(off, ox)
        oy_svg = mm_to_svg(h - sh - oh, oy)
        cls = "window" if otype == "window" else "door"
        lines.append(f'<rect x="{ox_svg:.1f}" y="{oy_svg:.1f}" width="{ow*SCALE:.1f}" height="{oh*SCALE:.1f}" class="{cls}"/>')
    
    # Dimensions
    dim_x = wx - 10
    lines.append(f'<line x1="{dim_x:.1f}" y1="{wy:.1f}" x2="{dim_x:.1f}" y2="{ground_y:.1f}" class="dim"/>')
    lines.append(f'<text x="{dim_x-2:.1f}" y="{(wy+ground_y)/2:.1f}" class="dim-text">{int(h)}</text>')
    
    dim_y = ground_y + 10
    lines.append(f'<line x1="{wx:.1f}" y1="{dim_y:.1f}" x2="{wx+ww:.1f}" y2="{dim_y:.1f}" class="dim"/>')
    lines.append(f'<text x="{wx+ww/2:.1f}" y="{dim_y+4:.1f}" class="dim-text">{int(wl)}</text>')
    
    lines.append(SVG_FOOT)
    svg_content = "\n".join(lines)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f: f.write(svg_content)
    return svg_content

# ============================================================
# 3. Section Detail
# ============================================================

def generate_section_svg(scene_dict, wall_id=None, position_mm=None, output_path=None):
    walls = scene_dict.get("walls", [])
    h, t = 2800, 120
    if walls:
        target = walls[0]
        if wall_id:
            tgt = next((w for w in walls if (isinstance(w,dict) and w.get("id")==wall_id) or (hasattr(w,'id') and w.id==wall_id)), None)
            if tgt: target = tgt
        h = _wh(target)
        t = target.get("thickness",120) if isinstance(target,dict) else (getattr(target,'thickness_mm',120) if hasattr(target,'thickness_mm') else 120)
    
    margin = 200
    svg_w = (t+600+2*margin)*SCALE
    svg_h = (h+600+2*margin)*SCALE
    lines = [SVG_HEAD.format(x=0,y=0,w=svg_w,h=svg_h)]
    ox, oy = margin+300, margin
    
    ww = t*SCALE; wh = h*SCALE
    wx, wy = mm_to_svg(0,ox), mm_to_svg(0,oy)
    
    lines.append(f'<rect x="{wx:.1f}" y="{wy:.1f}" width="{ww:.1f}" height="{wh:.1f}" class="hatch"/>')
    
    slab_h = 120*SCALE; ground_y = mm_to_svg(h,oy)
    lines.append(f'<rect x="{wx-30:.1f}" y="{ground_y:.1f}" width="{ww+60:.1f}" height="{slab_h:.1f}" fill="#999" stroke="#333" stroke-width="0.3"/>')
    
    beam_h = 300*SCALE
    lines.append(f'<rect x="{wx-20:.1f}" y="{wy-beam_h:.1f}" width="{ww+40:.1f}" height="{beam_h:.1f}" class="beam"/>')
    
    finish_t = 15*SCALE
    lines.append(f'<rect x="{wx-finish_t:.1f}" y="{wy:.1f}" width="{finish_t:.1f}" height="{wh:.1f}" fill="#ffe" stroke="#ccc" stroke-width="0.2"/>')
    lines.append(f'<rect x="{wx+ww:.1f}" y="{wy:.1f}" width="{finish_t:.1f}" height="{wh:.1f}" fill="#ffe" stroke="#ccc" stroke-width="0.2"/>')
    
    base_h = 80*SCALE
    lines.append(f'<rect x="{wx-finish_t:.1f}" y="{ground_y-base_h:.1f}" width="{ww+finish_t*2:.1f}" height="{base_h:.1f}" fill="#8B4513" stroke="#5C3317" stroke-width="0.2"/>')
    
    dim_x = wx-50
    lines.append(f'<line x1="{dim_x:.1f}" y1="{wy:.1f}" x2="{dim_x:.1f}" y2="{ground_y:.1f}" class="dim"/>')
    lines.append(f'<text x="{dim_x-5:.1f}" y="{(wy+ground_y)/2:.1f}" class="dim-text">{int(h)}</text>')
    
    ax = wx+ww+40
    for i,(y,txt) in enumerate([(wy+50,"1.Top finish"),(wy+wh*0.3,"2.Wall base"),(wy+wh*0.6,"3.Baseboard H=80"),(ground_y+50,"4.Cement screed"),(wy-beam_h+50,"5.Concrete lintel")]):
        lines.append(f'<text x="{ax:.1f}" y="{y:.1f}" class="label" font-size="2.5px" text-anchor="start">{txt}</text>')
        lines.append(f'<line x1="{ax-2:.1f}" y1="{y-1:.1f}" x2="{wx+ww:.1f}" y2="{y-1:.1f}" stroke="#f00" stroke-width="0.1" stroke-dasharray="1,1"/>')
    
    lines.append(SVG_FOOT)
    svg_content = "\n".join(lines)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f: f.write(svg_content)
    return svg_content

# ============================================================
# 4. Axonometric
# ============================================================

def generate_axonometric_svg(scene_dict, output_path=None):
    walls = scene_dict.get("walls", [])
    furniture = scene_dict.get("furniture", [])
    columns = scene_dict.get("columns", [])
    if not walls: return None
    
    def iso(x,y,z,cx,cz):
        a=math.radians(30)
        px=(x-cx-(z-cz))*math.cos(a)
        py=-(x-cx+(z-cz))*math.sin(a)-y
        return px*SCALE, py*SCALE
    
    xs,zs=[],[]
    for w in walls:
        xs.extend([_ws(w,0),_we(w,0)])
        zs.extend([_ws(w,2),_we(w,2)])
    cx,cz=(min(xs)+max(xs))/2,(min(zs)+max(zs))/2
    
    svg_w,svg_h=600,400
    ox,oy=svg_w/2,svg_h/2
    lines=[SVG_HEAD.format(x=0,y=0,w=svg_w,h=svg_h)]
    
    # Grid
    for i in range(-5,6):
        px1,py1=iso(i*2000+cx,0,min(zs)-1000,cx,cz)
        px2,py2=iso(i*2000+cx,0,max(zs)+1000,cx,cz)
        lines.append(f'<line x1="{px1+ox:.1f}" y1="{py1+oy:.1f}" x2="{px2+ox:.1f}" y2="{py2+oy:.1f}" class="grid"/>')
        px1,py1=iso(min(xs)-1000,0,i*2000+cz,cx,cz)
        px2,py2=iso(max(xs)+1000,0,i*2000+cz,cx,cz)
        lines.append(f'<line x1="{px1+ox:.1f}" y1="{py1+oy:.1f}" x2="{px2+ox:.1f}" y2="{py2+oy:.1f}" class="grid"/>')
    
    # Walls
    for w in walls:
        for y in [0,_wh(w)]:
            px1,py1=iso(_ws(w,0),y,_ws(w,2),cx,cz)
            px2,py2=iso(_we(w,0),y,_we(w,2),cx,cz)
            lines.append(f'<line x1="{px1+ox:.1f}" y1="{py1+oy:.1f}" x2="{px2+ox:.1f}" y2="{py2+oy:.1f}" stroke="#333" stroke-width="0.5"/>')
    
    # Furniture
    for f in furniture:
        pos=f.get("position",[0,0,0])
        px,py=iso(_xyz(pos,0),_xyz(pos,1),_xyz(pos,2),cx,cz)
        fw=f.get("width_mm",500)*SCALE
        fh=f.get("height_mm",500)*SCALE
        lines.append(f'<rect x="{px+ox-fw/2:.1f}" y="{py+oy-fh:.1f}" width="{fw:.1f}" height="{fh:.1f}" class="furniture"/>')
    
    # Columns
    for col in columns:
        cp=col.get("position",[0,0,0])
        px,py=iso(_xyz(cp,0),_xyz(cp,1),_xyz(cp,2),cx,cz)
        cw=col.get("width_mm",300)*SCALE
        ch=col.get("height_mm",2800)*SCALE
        lines.append(f'<rect x="{px+ox-cw/2:.1f}" y="{py+oy-ch:.1f}" width="{cw:.1f}" height="{ch:.1f}" class="column"/>')
    
    lines.append(SVG_FOOT)
    svg_content="\n".join(lines)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path,"w",encoding="utf-8") as f: f.write(svg_content)
    return svg_content

# ============================================================
# 5. Batch generate
# ============================================================


# ============================================================
# Dimension Annotation Overlay
# ============================================================

def _dim_annotation_svg(walls, rooms, offset_x=0, offset_y=0):
    """Generate SVG elements for dimension lines and labels."""
    elements = []
    scale = SCALE
    
    if not walls:
        return elements
    
    # Calculate bounds
    xs, zs = [], []
    for w in walls:
        xs.extend([_ws(w,0), _we(w,0)])
        zs.extend([_ws(w,2), _we(w,2)])
    if not xs:
        return elements
    
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    dim_offset = 1200  # Offset for dimension lines in mm
    
    # Horizontal dimension (bottom)
    y_pos = mm_to_svg(max_z + dim_offset, offset_y)
    sx, ex = mm_to_svg(min_x, offset_x), mm_to_svg(max_x, offset_x)
    elements.append(f'<line x1="{sx:.1f}" y1="{y_pos:.1f}" x2="{ex:.1f}" y2="{y_pos:.1f}" class="dim"/>')
    elements.append(f'<line x1="{sx:.1f}" y1="{mm_to_svg(max_z,offset_y):.1f}" x2="{sx:.1f}" y2="{y_pos:.1f}" class="dim"/>')
    elements.append(f'<line x1="{ex:.1f}" y1="{mm_to_svg(max_z,offset_y):.1f}" x2="{ex:.1f}" y2="{y_pos:.1f}" class="dim"/>')
    w_mm = max_x - min_x
    elements.append(f'<text x="{(sx+ex)/2:.1f}" y="{y_pos+5:.1f}" class="dim-text">{w_mm:.0f}mm</text>')
    
    # Vertical dimension (right)
    x_pos = mm_to_svg(max_x + dim_offset, offset_x)
    sz, ez = mm_to_svg(min_z, offset_y), mm_to_svg(max_z, offset_y)
    elements.append(f'<line x1="{x_pos:.1f}" y1="{sz:.1f}" x2="{x_pos:.1f}" y2="{ez:.1f}" class="dim"/>')
    elements.append(f'<line x1="{mm_to_svg(max_x,offset_x):.1f}" y1="{sz:.1f}" x2="{x_pos:.1f}" y2="{sz:.1f}" class="dim"/>')
    elements.append(f'<line x1="{mm_to_svg(max_x,offset_x):.1f}" y1="{ez:.1f}" x2="{x_pos:.1f}" y2="{ez:.1f}" class="dim"/>')
    d_mm = max_z - min_z
    elements.append(f'<text x="{x_pos+5:.1f}" y="{(sz+ez)/2:.1f}" class="dim-text" transform="rotate(90,{x_pos+5:.1f},{(sz+ez)/2:.1f})">{d_mm:.0f}mm</text>')
    
    return elements


def _room_label_svg(rooms, offset_x=0, offset_y=0):
    """Generate SVG room labels with area."""
    elements = []
    scale = SCALE
    for r in rooms:
        pts = r.get("floor_points", r.get("pts", []))
        if not pts:
            continue
        cx = sum(_xyz(p,0) for p in pts) / len(pts)
        cz = sum(_xyz(p,2) for p in pts) / len(pts)
        
        # Calculate area
        area = 0
        n = len(pts)
        for i in range(n):
            x1, z1 = _xyz(pts[i],0), _xyz(pts[i],2)
            x2, z2 = _xyz(pts[(i+1)%n],0), _xyz(pts[(i+1)%n],2)
            area += x1*z2 - x2*z1
        area_m2 = abs(area) / 2e6
        
        sx, sy = mm_to_svg(cx, offset_x), mm_to_svg(cz, offset_y)
        name = r.get("name", r.get("type", "Room"))
        elements.append(f'<text x="{sx:.1f}" y="{sy:.1f}" class="label" font-size="3.5">{name}</text>')
        elements.append(f'<text x="{sx:.1f}" y="{sy+4:.1f}" class="dim-text" font-size="2.5">{area_m2:.1f}m\u00b2</text>')
    
    return elements


def _title_block_svg(width_mm, offset_y):
    """Generate SVG title block at bottom."""
    elements = []
    h = 30  # title block height in SVG units
    y = offset_y + width_mm * SCALE + 40  # Below the drawing
    
    elements.append(f'<rect x="0" y="{y:.1f}" width="{width_mm*SCALE:.1f}" height="{h:.1f}" fill="none" stroke="#000" stroke-width="0.5"/>')
    elements.append(f'<text x="5" y="{y+12:.1f}" class="label" font-size="3">Interior Design - Floor Plan</text>')
    elements.append(f'<text x="5" y="{y+24:.1f}" class="dim-text" font-size="2.5">Scale: 1:100 | Unit: mm | AI-Assisted Design</text>')
    
    # North arrow
    nx = width_mm * SCALE - 20
    ny = y + 15
    elements.append(f'<circle cx="{nx:.1f}" cy="{ny:.1f}" r="8" fill="none" stroke="#000" stroke-width="0.3"/>')
    elements.append(f'<line x1="{nx:.1f}" y1="{ny-6:.1f}" x2="{nx:.1f}" y2="{ny+6:.1f}" stroke="#000" stroke-width="0.5"/>')
    elements.append(f'<line x1="{nx:.1f}" y1="{ny-6:.1f}" x2="{nx-2:.1f}" y2="{ny-3:.1f}" stroke="#000" stroke-width="0.3"/>')
    elements.append(f'<line x1="{nx:.1f}" y1="{ny-6:.1f}" x2="{nx+2:.1f}" y2="{ny-3:.1f}" stroke="#000" stroke-width="0.3"/>')
    elements.append(f'<text x="{nx:.1f}" y="{ny-8:.1f}" class="label" font-size="3" text-anchor="middle">N</text>')
    
    return elements


# Patch generate_all_drawings to include annotations

def generate_all_drawings(scene_dict, out_dir="output/drawings"):
    os.makedirs(out_dir, exist_ok=True)
    results={}
    
    plan=generate_furniture_plan_svg(scene_dict, f"{out_dir}/01_floor_plan.svg")
    if plan: results["furniture_plan"]=f"{out_dir}/01_floor_plan.svg"
    
    walls=scene_dict.get("walls",[])
    for i,w in enumerate(walls[:4]):
        wid=w.get("id","") if isinstance(w,dict) else (w.id if hasattr(w,'id') else str(i))
        elev_path=f"{out_dir}/02_elevation_wall_{i+1}.svg"
        generate_elevation_svg(scene_dict, wid, elev_path)
        results[f"elevation_{wid}"]=elev_path
    
    section_path=f"{out_dir}/03_section_detail.svg"
    generate_section_svg(scene_dict, output_path=section_path)
    results["section_detail"]=section_path
    
    axo_path=f"{out_dir}/04_axonometric.svg"
    generate_axonometric_svg(scene_dict, axo_path)
    if axo_path: results["axonometric"]=axo_path
    
    print(f"[construction_drawings] Generated {len(results)} drawings in {out_dir}/")
    return results

def svg_to_png(svg_path, png_path=None):
    if png_path is None: png_path=svg_path.replace(".svg",".png")
    try:
        import cairosvg
        cairosvg.svg2png(url=svg_path, write_to=png_path, output_width=2000)
        return png_path
    except BaseException: pass
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        drawing=svg2rlg(svg_path)
        renderPM.drawToFile(drawing, png_path, fmt="PNG")
        return png_path
    except BaseException: pass
    try:
        from core.svg_to_png_pil import svg_to_png as pil_convert
        return pil_convert(svg_path, png_path)
    except BaseException: pass
    return None