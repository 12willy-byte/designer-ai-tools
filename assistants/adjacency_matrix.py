# -*- coding: utf-8 -*-
"""
adjacency_matrix - Room functional relationship matrix & bubble diagram
Generates adjacency matrix, affinity scores, and bubble diagram SVG.
Core architectural programming tool.
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

# Affinity scores: 4=must adjacent, 3=should, 2=neutral, 1=avoid, 0=must separate
AFFINITY_MATRIX = {
    ("客厅","餐厅"):4,("客厅","厨房"):3,("客厅","主卧"):1,("客厅","卫生间"):1,
    ("餐厅","厨房"):4,("厨房","卫生间"):2,("厨房","阳台"):2,
    ("主卧","卫生间"):3,("主卧","书房"):2,("主卧","客厅"):1,
    ("卧室","卫生间"):2,("书房","客厅"):2,
    ("玄关","客厅"):3,("玄关","餐厅"):2,
    ("卫生间","客厅"):1,("卫生间","卧室"):3,
}

@dataclass
class AdjacencyReport:
    rooms: list; matrix: dict; scores: dict
    total_affinity: float; max_possible: float
    recommendations: list
    bubble_svg: str = ""

def analyze_adjacency(scene) -> AdjacencyReport:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    if len(rooms) < 2:
        return AdjacencyReport([], {}, {}, 0, 0, [])
    
    rtypes = [r.get('type','未分类') for r in rooms]
    rnames = [r.get('name', f'R{i}') for i,r in enumerate(rooms)]
    
    # Build matrix
    matrix = {}
    scores = {}
    total = 0; max_possible = 0
    
    for i in range(len(rooms)):
        for j in range(i+1, len(rooms)):
            pair = (rtypes[i], rtypes[j])
            rev_pair = (rtypes[j], rtypes[i])
            affinity = AFFINITY_MATRIX.get(pair, AFFINITY_MATRIX.get(rev_pair, 2))
            key = f"{rnames[i]}--{rnames[j]}"
            matrix[key] = affinity
            total += affinity
            max_possible += 4
    
    # Scores per room
    for i, rn in enumerate(rnames):
        room_score = 0
        for j in range(len(rooms)):
            if i == j: continue
            pair = (rtypes[i], rtypes[j])
            rev = (rtypes[j], rtypes[i])
            room_score += AFFINITY_MATRIX.get(pair, AFFINITY_MATRIX.get(rev, 2))
        scores[rn] = room_score
    
    # Recommendations
    recs = []
    for pair, score in matrix.items():
        if score <= 1:
            recs.append(f"避免 {pair} 相邻（亲和度{score}）")
        elif score == 4:
            recs.append(f"必须 {pair} 相邻（亲和度{score}）")
    
    # Bubble diagram SVG
    svg = _generate_bubble_svg(rnames, rtypes, matrix, rooms)
    
    return AdjacencyReport(rnames, matrix, scores, total, max_possible, recs, svg)

def _generate_bubble_svg(names, types, matrix, rooms):
    n = len(names)
    if n == 0: return ""
    
    r = 30; spacing = 80
    w = n * spacing + 80
    h = n * 50 + 80
    
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}mm" height="{h}mm">']
    lines.append('<style>.node{fill:#4a90d9;stroke:#2c5f8a;stroke-width:1.5}.node-label{fill:#fff;font-size:8px;text-anchor:middle}.edge{stroke:#ccc;stroke-width:1}.edge-strong{stroke:#e74c3c;stroke-width:2}</style>')
    
    # Nodes
    positions = []
    for i, (name, typ) in enumerate(zip(names, types)):
        x = 40 + (i % 3) * spacing
        y = 40 + (i // 3) * spacing
        positions.append((x, y))
        col = {"客厅":"#e74c3c","主卧":"#3498db","卧室":"#3498db","厨房":"#f39c12","卫生间":"#1abc9c","餐厅":"#e67e22","书房":"#9b59b6"}.get(typ,"#95a5a6")
        lines.append(f'<circle cx="{x}" cy="{y}" r="{r}" class="node" fill="{col}"/>')
        lines.append(f'<text x="{x}" y="{y+3}" class="node-label">{name[:4]}</text>')
    
    # Edges
    for i in range(n):
        for j in range(i+1, n):
            key = f"{names[i]}--{names[j]}"
            score = matrix.get(key, 2)
            if score >= 2:
                cls = "edge-strong" if score >= 4 else "edge"
                lines.append(f'<line x1="{positions[i][0]}" y1="{positions[i][1]}" x2="{positions[j][0]}" y2="{positions[j][1]}" class="{cls}"/>')
    
    lines.append('</svg>')
    return '\n'.join(lines)

def print_adjacency(ar):
    lines=["="*60,f"ADJACENCY MATRIX: Affinity {ar.total_affinity}/{ar.max_possible} ({ar.total_affinity/ar.max_possible*100:.0f}% optimal)","="*60]
    lines.append(f"\nPairwise:")
    for pair, score in sorted(ar.matrix.items(), key=lambda x:-x[1]):
        bar = "█" * score + "░" * (4-score)
        lines.append(f"  {pair}: {bar} ({score}/4)")
    lines.append(f"\nPer-room scores:")
    for rn, s in sorted(ar.scores.items(), key=lambda x:-x[1]):
        lines.append(f"  {rn}: {s}")
    if ar.recommendations:
        lines.append(f"\nRecommendations:")
        for r in ar.recommendations: lines.append(f"  - {r}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n