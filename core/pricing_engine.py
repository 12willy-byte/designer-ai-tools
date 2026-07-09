# -*- coding: utf-8 -*-
"""pricing_engine - Real-time cost estimation"""
import json, os, math, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

REGIONAL_MULTIPLIERS = {
    "一线": 1.25, "新一线": 1.12, "二线": 1.0, "三线": 0.82, "四线": 0.72,
    "national_avg": 1.0, "北京": 1.35, "上海": 1.35, "深圳": 1.30, "广州": 1.20,
    "杭州": 1.15, "成都": 1.05, "武汉": 1.0, "西安": 0.95,
}
BRAND_TIERS = {"budget": 0.7, "standard": 1.0, "premium": 1.5, "luxury": 2.5}

from core.scene_utils import normalize as _rd, get_rooms, get_walls

def get_material_price(name, region="national_avg", brand="standard"):
    db = {
        "地板_实木复合": ("m2", 280), "地板_强化": ("m2", 120), "地板_SPC": ("m2", 80),
        "瓷砖_800x800": ("m2", 110), "瓷砖_600x1200": ("m2", 150),
        "墙漆_乳胶漆": ("m2", 35), "墙漆_艺术漆": ("m2", 180),
        "墙砖": ("m2", 90), "吊顶_石膏板": ("m2", 120), "吊顶_铝扣板": ("m2", 150),
        "定制柜体": ("m2", 1000), "室内门_实木": ("樘", 2500), "室内门_烤漆": ("樘", 1500),
        "窗户_断桥铝": ("m2", 600),
    }
    for k, (unit, price) in db.items():
        if name in k or k in name:
            rm = REGIONAL_MULTIPLIERS.get(region, 1.0)
            bm = BRAND_TIERS.get(brand, 1.0)
            return {"name": k, "unit": unit, "final_price": round(price * rm * bm, 2)}

def estimate_total_cost(scene, region="national_avg", brand="standard",
                        design_fee_pct=0.08, mgmt_pct=0.05, contingency_pct=0.05):
    rooms_raw = get_rooms(scene)
    walls_raw = get_walls(scene)
    rooms = [_rd(r) for r in rooms_raw]
    walls = [_rd(w) for w in walls_raw]
    
    total_floor = sum(r.get('length_mm',4000)*r.get('width_mm',3500)/1e6 for r in rooms)
    
    # Wall area (rough)
    total_wall = total_floor * 2.5
    
    rm = REGIONAL_MULTIPLIERS.get(region, 1.0)
    bm = BRAND_TIERS.get(brand, 1.0)
    
    breakdown = {
        "demolition": ("拆除工程", total_floor, "m2", round(45*rm,2), round(45*rm*total_floor,2)),
        "electrical": ("水电改造", total_floor, "m2", round(120*rm,2), round(120*rm*total_floor,2)),
        "waterproof": ("防水工程", total_floor*0.3, "m2", round(55*rm,2), round(55*rm*total_floor*0.3,2)),
        "masonry": ("泥瓦工程", total_floor+total_wall*0.5, "m2", round(65*rm,2), round(65*rm*(total_floor+total_wall*0.5),2)),
        "carpentry": ("木工工程", total_floor*0.6, "m2", round(90*rm,2), round(90*rm*total_floor*0.6,2)),
        "painting": ("油漆工程", total_wall, "m2", round(45*rm,2), round(45*rm*total_wall,2)),
        "flooring": ("地板铺设", total_floor, "m2", round(150*rm*bm,2), round(150*rm*bm*total_floor,2)),
        "doors_windows": ("门窗工程", 4, "套", round(2000*rm*bm,2), round(2000*rm*bm*4,2)),
        "kitchen_bath": ("厨卫设备", 2, "套", round(15000*rm*bm,2), round(15000*rm*bm*2,2)),
        "custom_cabinets": ("定制柜体", total_wall*0.15, "m2", round(1000*rm*bm,2), round(1000*rm*bm*total_wall*0.15,2)),
    }
    
    hard = sum(v[4] for v in breakdown.values())
    design_fee = hard * design_fee_pct
    mgmt = hard * mgmt_pct
    contingency = hard * contingency_pct
    soft = hard * 0.3
    appliances = hard * 0.15
    total = hard + design_fee + mgmt + contingency + soft + appliances
    
    return {
        "project_info": {"total_area_m2": round(total_floor,1), "region": region, "brand": brand, "date": datetime.now().strftime("%Y-%m-%d")},
        "breakdown": {k: {"description": v[0], "quantity": round(v[1],1), "unit": v[2], "unit_price": v[3], "total": v[4]} for k,v in breakdown.items()},
        "summary": {
            "hard_decoration": round(hard,2), "design_fee": round(design_fee,2),
            "management_fee": round(mgmt,2), "contingency": round(contingency,2),
            "soft_decoration": round(soft,2), "appliances": round(appliances,2),
            "grand_total": round(total,2), "per_sqm": round(total/total_floor,2) if total_floor > 0 else 0,
        },
        "note": "Estimates only. Get 3+ contractor quotes."
    }