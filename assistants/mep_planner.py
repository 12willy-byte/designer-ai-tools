# -*- coding: utf-8 -*-
"""
mep_planner - MEP (Mechanical, Electrical, Plumbing) planning
Water supply, drainage, HVAC ducting, ventilation.
Based on GB 50015 (water supply) and GB 50736 (HVAC).
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass
class PlumbingPoint:
    id: str; room: str; type: str  # cold/hot/drain/gas/vent
    position_mm: list; height_mm: int
    diameter_mm: int; material: str; note: str = ""

@dataclass
class HVACZone:
    id: str; room: str; area_m2: float
    ac_type: str  # split/duct/radiant/vrf
    capacity_kw: float; airflow_m3h: float
    supply_pos: list; return_pos: list

@dataclass
class MEPPlan:
    plumbing: list; hvac: list
    water_supply_main_mm: int; drain_main_mm: int
    total_ac_capacity_kw: float

PLUMBING_RULES = {
    "厨房": [
        {"type":"cold","height":500,"dia":20,"mat":"PPR","note":"水槽冷水"},
        {"type":"hot","height":500,"dia":20,"mat":"PPR","note":"水槽热水"},
        {"type":"drain","height":450,"dia":50,"mat":"PVC","note":"水槽排水"},
        {"type":"gas","height":1500,"dia":15,"mat":"镀锌管","note":"燃气灶"},
    ],
    "卫生间": [
        {"type":"cold","height":300,"dia":20,"mat":"PPR","note":"马桶/洗手台"},
        {"type":"cold","height":1200,"dia":20,"mat":"PPR","note":"淋浴冷水"},
        {"type":"hot","height":1200,"dia":20,"mat":"PPR","note":"淋浴热水"},
        {"type":"drain","height":300,"dia":110,"mat":"PVC","note":"马桶排污"},
        {"type":"drain","height":0,"dia":50,"mat":"PVC","note":"地漏"},
        {"type":"drain","height":500,"dia":50,"mat":"PVC","note":"洗手台排水"},
        {"type":"vent","height":2500,"dia":75,"mat":"PVC","note":"排气扇"},
    ],
    "阳台": [
        {"type":"cold","height":300,"dia":20,"mat":"PPR","note":"洗衣机"},
        {"type":"drain","height":300,"dia":50,"mat":"PVC","note":"洗衣机排水"},
        {"type":"drain","height":0,"dia":50,"mat":"PVC","note":"阳台地漏"},
    ],
}

HVAC_COOLING = {"客厅":180,"主卧":160,"卧室":150,"厨房":200,"餐厅":170,"书房":160,"卫生间":120}

def generate_mep_plan(scene) -> MEPPlan:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    plumbing = []; hvac = []; pid = 0; hid = 0
    
    for r in rooms:
        rt = r.get('type',''); nm = r.get('name','')
        rl = r.get('length_mm',4000); rw = r.get('width_mm',3500)
        area = rl*rw/1e6; l=r.get('length_mm',4000)/1000; w=r.get('width_mm',3500)/1000
        
        # Plumbing
        rules = PLUMBING_RULES.get(rt, [])
        for rule in rules:
            pid += 1
            plumbing.append(PlumbingPoint(
                f"P{pid:03d}", nm, rule['type'],
                [int(rl*0.3), 0, int(rw*0.5)],
                rule['height'], rule['dia'], rule['mat'], rule['note']
            ))
        
        # HVAC
        if area > 3 and rt in HVAC_COOLING:
            cw = HVAC_COOLING.get(rt, 150)
            cap = round(area * cw / 1000, 1)
            af = round(cap * 500)  # m3/h airflow
            hid += 1
            hvac.append(HVACZone(
                f"H{hid:03d}", nm, round(area,1),
                "split" if area<30 else "duct",
                cap, af,
                [int(rl*0.3), 2600, int(rw*0.4)],
                [int(rl*0.7), 2600, int(rw*0.4)],
            ))
    
    w_count = sum(1 for p in plumbing if p.type=='cold')
    d_count = sum(1 for p in plumbing if p.type=='drain' and p.diameter_mm>=110)
    
    return MEPPlan(
        plumbing, hvac,
        25 if w_count>3 else 20,
        110 if d_count>1 else 75,
        round(sum(h.capacity_kw for h in hvac),1),
    )

def print_mep_plan(mep):
    lines=["="*60,f"MEP PLAN: Plumbing({len(mep.plumbing)}pts) + HVAC({len(mep.hvac)}zones)","="*60]
    lines.append(f"\nWATER: main cold D{mep.water_supply_main_mm}mm | main drain D{mep.drain_main_mm}mm")
    by_room = {}
    for p in mep.plumbing:
        by_room.setdefault(p.room, []).append(p)
    for room, pts in by_room.items():
        lines.append(f"\n  {room}:")
        for p in pts:
            lines.append(f"    [{p.id}] {p.type} D{p.diameter_mm}mm {p.material} @H={p.height_mm}mm | {p.note}")
    lines.append(f"\nHVAC: {len(mep.hvac)} zones | Total {mep.total_ac_capacity_kw}kW")
    for h in mep.hvac:
        lines.append(f"  [{h.id}] {h.room} {h.area_m2}m2 | {h.ac_type} | {h.capacity_kw}kW | {h.airflow_m3h}m3/h")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n