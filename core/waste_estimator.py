# -*- coding: utf-8 -*-
"""
waste_estimator - Construction waste estimation & environmental impact
Estimates demolition waste, packaging waste, and recycling potential.
Based on typical Chinese construction waste ratios.
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

WASTE_RATES = {"concrete":0.03,"brick":0.05,"wood":0.08,"gypsum":0.10,"tile":0.08,"paint":0.02,"packaging":0.05}
RECYCLING_RATES = {"concrete":0.80,"brick":0.70,"wood":0.50,"gypsum":0.30,"tile":0.40,"metal":0.95,"packaging":0.85}
DENSITY = {"concrete":2400,"brick":1800,"wood":600,"gypsum":800,"tile":2000,"packaging":100}

@dataclass
class WasteItem:
    material: str; volume_m3: float; weight_kg: float
    recyclable_kg: float; landfill_kg: float; disposal_cost: float

@dataclass
class WasteReport:
    items: list; total_weight_kg: float; total_volume_m3: float
    recycling_rate: float; total_cost: float
    co2_saved_kg: float; recommendations: list

def estimate_waste(scene) -> WasteReport:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    walls = [_n(w) for w in (getattr(scene,'walls',[]) or [])]
    
    total_floor = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms)
    
    # Wall volume (for demolition estimate)
    wall_vol = 0
    for w in walls:
        s, e = w.get('start',[0,0,0]), w.get('end',[0,0,0])
        L = w.get('length_mm',0) or math.hypot(e[0]-s[0], e[2]-s[2]) if isinstance(e,(list,tuple)) and len(e)>=3 else 0
        H = w.get('height', w.get('height_mm',2800))
        T = w.get('thickness', w.get('thickness_mm',120))
        wall_vol += L * H * T / 1e9  # m3
    
    items = []
    total_w = 0; total_v = 0; total_rec = 0; total_cost = 0
    
    # Concrete waste from demolition
    if wall_vol > 0:
        waste_vol = wall_vol * WASTE_RATES["concrete"]
        weight = waste_vol * DENSITY["concrete"]
        rec = weight * RECYCLING_RATES["concrete"]
        items.append(WasteItem("混凝土", round(waste_vol,2), round(weight), round(rec), round(weight-rec), round(weight*0.08)))
        total_w += weight; total_v += waste_vol; total_rec += rec; total_cost += weight*0.08
    
    # Brick waste
    brick_waste = wall_vol * 0.3 * WASTE_RATES["brick"]
    brick_w = brick_waste * DENSITY["brick"]
    brick_rec = brick_w * RECYCLING_RATES["brick"]
    if brick_w > 50:
        items.append(WasteItem("砖块", round(brick_waste,2), round(brick_w), round(brick_rec), round(brick_w-brick_rec), round(brick_w*0.06)))
        total_w += brick_w; total_v += brick_waste; total_rec += brick_rec; total_cost += brick_w*0.06
    
    # Gypsum board waste
    gyp_area = total_floor * 1.5  # Ceiling + partition
    gyp_vol = gyp_area * 0.012 * WASTE_RATES["gypsum"]  # 12mm thick
    gyp_w = gyp_vol * DENSITY["gypsum"]
    gyp_rec = gyp_w * RECYCLING_RATES["gypsum"]
    items.append(WasteItem("石膏板", round(gyp_vol,2), round(gyp_w), round(gyp_rec), round(gyp_w-gyp_rec), round(gyp_w*0.10)))
    total_w += gyp_w; total_v += gyp_vol; total_rec += gyp_rec; total_cost += gyp_w*0.10
    
    # Tile waste
    tile_floor = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms if r.get('type','') in ('厨房','kitchen','卫生间','bathroom'))
    tile_vol = tile_floor * 0.01 * WASTE_RATES["tile"]
    tile_w = tile_vol * DENSITY["tile"]
    tile_rec = tile_w * RECYCLING_RATES["tile"]
    items.append(WasteItem("瓷砖", round(tile_vol,2), round(tile_w), round(tile_rec), round(tile_w-tile_rec), round(tile_w*0.08)))
    total_w += tile_w; total_v += tile_vol; total_rec += tile_rec; total_cost += tile_w*0.08
    
    # Packaging
    pkg_w = total_floor * 5  # ~5 kg per m2
    pkg_rec = pkg_w * RECYCLING_RATES["packaging"]
    items.append(WasteItem("包装材料", round(pkg_w/DENSITY["packaging"],2), round(pkg_w), round(pkg_rec), round(pkg_w-pkg_rec), round(pkg_w*0.05)))
    total_w += pkg_w; total_v += pkg_w/DENSITY["packaging"]; total_rec += pkg_rec; total_cost += pkg_w*0.05
    
    rec_rate = total_rec / total_w * 100 if total_w > 0 else 0
    co2_saved = total_rec * 0.5  # ~0.5 kg CO2 saved per kg recycled
    
    recs = [
        f"总废料: {total_w:.0f}kg | 可回收: {rec_rate:.0f}%",
        "分类堆放: 混凝土/砖块/木材/包装 分别处置",
        f"推荐使用建筑垃圾资源化处理厂（回收率可提升至85%+）",
    ]
    
    return WasteReport(items, round(total_w), round(total_v,1), round(rec_rate,1), round(total_cost), round(co2_saved), recs)

def print_waste(wr):
    lines=["="*60,f"WASTE ESTIMATE: {wr.total_weight_kg}kg | Recycling: {wr.recycling_rate}%","="*60]
    for w in wr.items:
        lines.append(f"  {w.material}: {w.weight_kg}kg ({w.volume_m3}m3) | Recyclable: {w.recyclable_kg}kg | Cost: {w.disposal_cost}")
    lines.append(f"\nTotal Disposal Cost: {wr.total_cost} | CO2 Saved: {wr.co2_saved_kg}kg")
    if wr.recommendations:
        lines.append(f"\nRecommendations:")
        for r in wr.recommendations: lines.append(f"  - {r}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n