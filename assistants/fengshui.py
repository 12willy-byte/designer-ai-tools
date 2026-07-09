# -*- coding: utf-8 -*-
"""
fengshui - Traditional Chinese Feng Shui analysis
Door orientation, room placement, bed/desk positioning, color elements.
Based on classical Form School and Compass School principles.
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

FIVE_ELEMENTS = {"木":"wood","火":"fire","土":"earth","金":"metal","水":"water"}
ELEMENT_COLORS = {"wood":["green","teal"],"fire":["red","orange","purple"],"earth":["yellow","brown","beige"],"metal":["white","gold","silver"],"water":["black","blue","dark"]}
ROOM_ELEMENTS = {"客厅":"fire","主卧":"earth","卧室":"earth","厨房":"fire","卫生间":"water","书房":"wood","餐厅":"earth","玄关":"metal"}

@dataclass
class FengShuiItem:
    id: str; category: str; auspicious: bool
    detail: str; remedy: str = ""

@dataclass
class FengShuiReport:
    items: list; good_count: int; bad_count: int
    overall: str; element_balance: dict

def analyze_fengshui(scene) -> FengShuiReport:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    doors = [_n(d) for d in (getattr(scene,'doors',[]) or [])]
    windows = [_n(w) for w in (getattr(scene,'windows',[]) or [])]
    
    items = []
    
    # 1. Entry door alignment (大门不宜直对阳台/窗 - 穿堂煞)
    has_balcony = any(r.get('type','') in ('阳台','balcony') for r in rooms)
    entry_doors = [d for d in doors if d.get('type','')=='entry' or '入户' in str(d)]
    has_windows = len(windows) > 0
    
    # Simplified: warn if entry has direct line to window
    if has_balcony and has_windows:
        items.append(FengShuiItem("FS01","穿堂煞",False,
            "入户门可能直对阳台/窗,形成穿堂煞",
            "设玄关屏风或透光隔断阻断视线"))
    
    # 2. Bed position (床头靠实墙)
    bedrooms = [r for r in rooms if r.get('type','') in ('主卧','卧室','bedroom')]
    for br in bedrooms:
        items.append(FengShuiItem("FS02","床头靠山",True,
            f"{br.get('name','')}床头应靠实墙(不宜靠窗)",
            "床头靠实体墙,避开横梁压顶"))
    
    # 3. Kitchen-stove position (灶台不宜对门)
    kitchens = [r for r in rooms if r.get('type','') in ('厨房','kitchen')]
    if kitchens:
        items.append(FengShuiItem("FS03","灶台方位",True,
            "灶台不宜正对厨房门(财气外泄)",
            "灶台与门错开,或设半高隔断"))
    
    # 4. Bathroom door (卫生间门不宜对床/大门)
    bathrooms = [r for r in rooms if r.get('type','') in ('卫生间','bathroom')]
    if bathrooms:
        items.append(FengShuiItem("FS04","卫生间门",True,
            "卫生间门不宜正对大门或卧室门",
            "常关门+挂门帘,或调整开门方向"))
    
    # 5. Beam压迫 (横梁压顶)
    items.append(FengShuiItem("FS05","横梁压顶",True,
        "床/沙发/餐桌上方避免横梁",
        "吊顶包梁或避开梁下布置"))
    
    # 6. Mirror placement
    items.append(FengShuiItem("FS06","镜面位置",True,
        "镜子不宜正对床或大门",
        "镜面侧置或加柜门隐藏"))
    
    # 7. Element balance
    elements = {}
    for r in rooms:
        rt = r.get('type','')
        elem = ROOM_ELEMENTS.get(rt,'earth')
        elements[elem] = elements.get(elem,0) + 1
    
    good = sum(1 for i in items if i.auspicious)
    bad = sum(1 for i in items if not i.auspicious)
    
    if bad == 0:
        overall = "风水格局良好,无明显冲煞"
    elif bad <= 2:
        overall = f"有{bad}处需注意,可通过软装化解"
    else:
        overall = f"{bad}处冲煞需化解,建议咨询专业风水师"
    
    return FengShuiReport(items, good, bad, overall, elements)

def print_fengshui(fr):
    lines=["="*60,f"FENG SHUI ANALYSIS",f"Overall: {fr.overall}","="*60]
    for i in fr.items:
        icon = "AUSP" if i.auspicious else "FIX"
        lines.append(f"  [{icon}] [{i.category}] {i.detail}")
        if i.remedy: lines.append(f"       -> {i.remedy}")
    if fr.element_balance:
        lines.append(f"\n五 行 平 衡:")
        for e,c in fr.element_balance.items():
            lines.append(f"  {e}: {c}间 ({ELEMENT_COLORS.get(e,['?'])[0]})")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n