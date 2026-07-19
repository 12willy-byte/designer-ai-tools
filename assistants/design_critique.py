# -*- coding: utf-8 -*-
"""design_critique - AI Design Critique Engine"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field
from enum import Enum

class Sev(Enum):
    C = "critical"; M = "major"; m = "minor"; S = "suggestion"; P = "praise"; I = "info"

@dataclass
class Item:
    id: str; cat: str; sev: Sev; title: str; detail: str; loc: str = ""; sug: str = ""; ref: str = ""

@dataclass
class Critique:
    name: str; score: float; summary: str
    items: list = field(default_factory=list)
    good: list = field(default_factory=list)
    fix: list = field(default_factory=list)
    risk: list = field(default_factory=list)

from core.scene_utils import normalize as _n
def critique_design(scene, conds=None, ai=None):
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    walls = [_n(w) for w in (getattr(scene,'walls',[]) or [])]
    doors = [_n(d) for d in (getattr(scene,'doors',[]) or [])]
    windows = [_n(w) for w in (getattr(scene,'windows',[]) or [])]
    items, good, fix, risk = [], [], [], []
    n = len(rooms)
    total = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms)

    # 1. Space
    if total > 0:
        items.append(Item("SP01", "空间", Sev.I, f"总面积{total:.1f}m2 {n}间", f"均{total/n:.1f}m2/间" if n else ""))
    for r in rooms:
        rl = r.get('length_mm',0)/1000; rw = r.get('width_mm',0)/1000
        nm = r.get('name','?')
        if rl>0 and rw>0:
            ratio = max(rl,rw)/min(rl,rw)
            if ratio>3: items.append(Item("SP02","空间比例",Sev.M,f"{nm}过长{ratio:.1f}:1",f"{rl:.1f}x{rw:.1f}m",sug="家具分区改善比例感",ref="GB50096面宽>=3m"))
            elif ratio>2: items.append(Item("SP03","空间比例",Sev.m,f"{nm}偏长{ratio:.1f}:1",f"{rl:.1f}x{rw:.1f}m",sug="横向家具布局"))
            else: good.append(f"空间比例{ratio:.1f}:1理想")
        area = r.get('length_mm',0)*r.get('width_mm',0)/1e6
        rt = r.get('type','')
        mins = {"客厅":10,"主卧":9,"卧室":7,"厨房":4,"卫生间":2.5,"书房":6}
        ma = mins.get(rt,6)
        if 0<area<ma: items.append(Item("SP04","面积",Sev.M,f"{nm}{area:.1f}m2<{ma}m2",f"不足{rt}标准",sug=f"扩大至>={ma}m2",ref="GB50096"))

    # 2. Flow
    if not doors: items.append(Item("TF01","动线",Sev.m,"无门数据",sug="添加门位置"))
    elif n>3:
        has_hall = any(r.get('type','') in ('走廊','hallway','玄关') for r in rooms)
        if not has_hall: items.append(Item("TF02","动线",Sev.m,"缺走廊","多房间可能穿套",sug="确保卧室不互穿")); risk.append("穿套影响隐私")

    # 3. Light
    wa = sum(w.get('width_mm',0)*w.get('height_mm',0)/1e6 for w in windows)
    if total>0:
        wfr = wa/total
        if wfr<0.07: items.append(Item("NL01","采光",Sev.M,f"窗地比{wfr:.1%}<7%",sug="增大窗或加天窗",ref="GB50033>=1/7"))
        elif wfr<0.12: items.append(Item("NL02","采光",Sev.m,f"窗地比{wfr:.1%}偏小",sug="考虑扩大主窗"))
        elif wfr>0.2: good.append(f"窗地比{wfr:.1%}优秀"); items.append(Item("NL03","采光",Sev.P,f"窗地比{wfr:.1%}充足"))

    # 4. Storage
    sa = sum(r.get('length_mm',0)*r.get('width_mm',0)/1e6 for r in rooms if r.get('type','') in ('储物间','衣帽间'))
    if total>50 and sa<total*0.05: items.append(Item("ST01","收纳",Sev.m,f"收纳{sa:.1f}m2<5%",sug="增加柜体至8-12%"))

    # 5. Furniture fit
    for r in rooms:
        rt=r.get('type',''); nm=r.get('name',''); rw=r.get('width_mm',0)/1000
        if rt in ('主卧','bedroom') and 0<rw<2.8: items.append(Item("FS01","家具",Sev.M,f"{nm}面宽{rw:.1f}m",sug="1.8m床需>=3.0m面宽"))
        if rt in ('客厅','living_room') and 0<rw<3.0: items.append(Item("FS02","家具",Sev.m,f"{nm}面宽{rw:.1f}m",sug="紧凑沙发<900mm深"))

    # 6. Height check
    for r in rooms:
        h = r.get('height_mm',2800)/1000; nm=r.get('name','')
        if h<2.4: items.append(Item("CC01","规范",Sev.C,f"{nm}层高{h:.1f}m<2.4m",ref="GB50096净高>=2.4m"))
        elif h<2.6: items.append(Item("CC02","规范",Sev.m,f"{nm}层高{h:.1f}m偏矮"))
        else: good.append(f"层高{h:.1f}m达标")

    # 7. Door width
    for d in doors:
        dw = d.get('width_mm',0)
        if 0<dw<700: items.append(Item("CC03","规范",Sev.C,f"门宽{dw}mm<700",ref="GB50096>=800mm"))
        elif 0<dw<800: items.append(Item("CC04","规范",Sev.m,f"门宽{dw}mm偏窄",sug="建议>=800mm"))

    # 8. Safety
    for w in windows:
        sh = w.get('sill_height_mm',0)
        if 0<sh<900: items.append(Item("SF01","安全",Sev.M,f"窗台{sh}mm<900",sug="加装护栏",ref="GB50096"))

    # Score
    cc = sum(1 for i in items if i.sev==Sev.C)
    mc = sum(1 for i in items if i.sev==Sev.M)
    m2 = sum(1 for i in items if i.sev==Sev.m)
    pc = sum(1 for i in items if i.sev==Sev.P)
    score = max(0, min(100, 70-cc*15-mc*5-m2*2+pc*3))
    
    if score>=90: sm="优秀,仅需微调"
    elif score>=75: sm=f"良好,{mc}个主要问题"
    elif score>=60: sm=f"一般,{cc}严重+{mc}主要问题"
    else: sm=f"需大改,{cc}个严重问题"
    
    return Critique(
        name=getattr(scene,'name','?'),
        score=score, summary=sm,
        items=[i for i in items if i.sev!=Sev.P],
        good=good, risk=risk,
        fix=[f"{i.title}: {i.sug}" for i in items if i.sev in (Sev.C,Sev.M)],
    )

def print_critique(cr):
    lines=["="*60,f"DESIGN CRITIQUE: {cr.name}",f"Score: {cr.score:.0f}/100 {cr.summary}","="*60]
    if cr.good:
        lines.append("\nSTRENGTHS:")
        for g in cr.good[:8]: lines.append(f"  {g}")
    if cr.risk:
        lines.append("\nRISKS:")
        for r in cr.risk: lines.append(f"  {r}")
    if cr.items:
        lines.append(f"\nISSUES ({len(cr.items)}):")
        icons={Sev.C:"RED",Sev.M:"ORG",Sev.m:"YLW",Sev.I:"BLU",Sev.P:"GRN"}
        for i in cr.items:
            lines.append(f"  [{icons.get(i.sev,'?')}] [{i.cat}] {i.title}")
            lines.append(f"     {i.detail}")
            if i.sug: lines.append(f"     -> {i.sug}")
            if i.ref: lines.append(f"     GB: {i.ref}")
    if cr.fix:
        lines.append(f"\nTOP FIXES:")
        for f in cr.fix[:5]: lines.append(f"  {f}")
    lines.append("="*60)
    t="\n".join(lines)
    print(t)
    return t