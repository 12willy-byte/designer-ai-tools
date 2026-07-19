"""家具库扩展：家电、卫浴洁具、五金配件"""
from dataclasses import dataclass, field

EXTRA_FURNITURE = """
{
  "appliances": [
    {"id":"app-fridge-2door","name":"双门冰箱","category":"appliance","subcategory":"refrigerator","width_mm":600,"depth_mm":650,"height_mm":1800,"clearance_front_mm":900,"material_type":"metal","styles":["modern"],"price_range_low":2000,"price_range_high":6000,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"app-fridge-french","name":"法式冰箱","category":"appliance","subcategory":"refrigerator","width_mm":900,"depth_mm":700,"height_mm":1800,"clearance_front_mm":1000,"material_type":"metal","styles":["modern","luxury"],"price_range_low":4000,"price_range_high":12000,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"app-oven-builtin","name":"嵌入式烤箱","category":"appliance","subcategory":"oven","width_mm":600,"depth_mm":550,"height_mm":600,"material_type":"metal","styles":["modern"],"price_range_low":2000,"price_range_high":8000,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"app-microwave","name":"微波炉","category":"appliance","subcategory":"microwave","width_mm":500,"depth_mm":400,"height_mm":310,"material_type":"metal","styles":["modern"],"price_range_low":300,"price_range_high":1500,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"app-hood","name":"抽油烟机","category":"appliance","subcategory":"range-hood","width_mm":900,"depth_mm":500,"height_mm":650,"material_type":"metal","styles":["modern"],"price_range_low":1500,"price_range_high":5000,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"app-cooktop","name":"燃气灶","category":"appliance","subcategory":"cooktop","width_mm":750,"depth_mm":450,"height_mm":150,"material_type":"metal","styles":["modern"],"price_range_low":800,"price_range_high":3000,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"app-dishwasher","name":"洗碗机","category":"appliance","subcategory":"dishwasher","width_mm":600,"depth_mm":580,"height_mm":850,"clearance_front_mm":800,"material_type":"metal","styles":["modern"],"price_range_low":2500,"price_range_high":8000,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"app-washer","name":"洗衣机","category":"appliance","subcategory":"washer","width_mm":600,"depth_mm":550,"height_mm":850,"clearance_front_mm":700,"material_type":"metal","styles":["modern"],"price_range_low":1500,"price_range_high":5000,"suitable_rooms":["bathroom","balcony"],"capacity":0},
    {"id":"app-dryer","name":"烘干机","category":"appliance","subcategory":"dryer","width_mm":600,"depth_mm":550,"height_mm":850,"clearance_front_mm":700,"material_type":"metal","styles":["modern"],"price_range_low":2000,"price_range_high":6000,"suitable_rooms":["bathroom","balcony"],"capacity":0},
    {"id":"app-tv-55","name":"电视 55寸","category":"appliance","subcategory":"tv","width_mm":1230,"depth_mm":80,"height_mm":720,"material_type":"composite","styles":["modern"],"price_range_low":2000,"price_range_high":6000,"suitable_rooms":["living"],"capacity":0},
    {"id":"app-tv-65","name":"电视 65寸","category":"appliance","subcategory":"tv","width_mm":1450,"depth_mm":80,"height_mm":840,"material_type":"composite","styles":["modern"],"price_range_low":3000,"price_range_high":9000,"suitable_rooms":["living"],"capacity":0},
    {"id":"app-ac-split","name":"空调挂机","category":"appliance","subcategory":"ac","width_mm":850,"depth_mm":220,"height_mm":300,"material_type":"composite","styles":["modern"],"price_range_low":2000,"price_range_high":5000,"suitable_rooms":["bedroom","living","study"],"capacity":0}
  ],
  "plumbing": [
    {"id":"plm-shower","name":"淋浴花洒","category":"fixture","subcategory":"shower","width_mm":200,"depth_mm":200,"height_mm":1100,"material_type":"metal","styles":["modern"],"price_range_low":300,"price_range_high":2000,"suitable_rooms":["bathroom"],"capacity":0},
    {"id":"plm-bathtub","name":"浴缸","category":"fixture","subcategory":"bathtub","width_mm":1600,"depth_mm":750,"height_mm":600,"clearance_front_mm":700,"material_type":"composite","styles":["modern","luxury"],"price_range_low":2000,"price_range_high":8000,"suitable_rooms":["bathroom"],"capacity":0},
    {"id":"plm-sink-kitchen","name":"厨房水槽","category":"fixture","subcategory":"sink","width_mm":800,"depth_mm":500,"height_mm":220,"material_type":"metal","styles":["modern"],"price_range_low":300,"price_range_high":1500,"suitable_rooms":["kitchen"],"capacity":0},
    {"id":"plm-sink-bath","name":"洗手盆","category":"fixture","subcategory":"sink","width_mm":600,"depth_mm":480,"height_mm":200,"material_type":"composite","styles":["modern"],"price_range_low":200,"price_range_high":1200,"suitable_rooms":["bathroom"],"capacity":0},
    {"id":"plm-bidet","name":"智能马桶","category":"fixture","subcategory":"toilet","width_mm":420,"depth_mm":720,"height_mm":520,"clearance_front_mm":600,"clearance_sides_mm":200,"material_type":"composite","styles":["modern"],"price_range_low":1500,"price_range_high":5000,"suitable_rooms":["bathroom"],"capacity":0},
    {"id":"plm-heater","name":"热水器","category":"appliance","subcategory":"water-heater","width_mm":350,"depth_mm":160,"height_mm":550,"material_type":"metal","styles":["modern"],"price_range_low":800,"price_range_high":2500,"suitable_rooms":["kitchen","bathroom"],"capacity":0}
  ],
  "hardware": [
    {"id":"hw-curtain-rod","name":"窗帘杆","category":"hardware","subcategory":"curtain-rod","width_mm":2000,"depth_mm":50,"height_mm":30,"material_type":"metal","styles":["modern"],"price_range_low":50,"price_range_high":300,"suitable_rooms":["living","bedroom"],"capacity":0},
    {"id":"hw-towel-rack","name":"毛巾架","category":"hardware","subcategory":"towel-rack","width_mm":600,"depth_mm":80,"height_mm":120,"material_type":"metal","styles":["modern"],"price_range_low":50,"price_range_high":200,"suitable_rooms":["bathroom"],"capacity":0},
    {"id":"hw-mirror-bath","name":"浴室镜","category":"hardware","subcategory":"mirror","width_mm":800,"depth_mm":30,"height_mm":600,"material_type":"glass","styles":["modern"],"price_range_low":200,"price_range_high":1000,"suitable_rooms":["bathroom"],"capacity":0}
  ]
}
"""

import json
EXTRA = json.loads(EXTRA_FURNITURE)

def merge_into_library():
    """合并额外家具到主库"""
    from core.furniture_library import FurnitureSpec, get_library, FurnitureLibrary
    lib = get_library()
    count = 0
    for cat, items in EXTRA.items():
        for item in items:
            if item["id"] not in lib.catalog:
                spec = FurnitureSpec(
                    id=item["id"], name=item["name"], category=item["category"],
                    subcategory=item.get("subcategory",""), width_mm=item["width_mm"],
                    depth_mm=item["depth_mm"], height_mm=item["height_mm"],
                    clearance_front_mm=item.get("clearance_front_mm",600),
                    clearance_sides_mm=item.get("clearance_sides_mm",100),
                    material_type=item.get("material_type","metal"),
                    styles=item.get("styles",["modern"]),
                    price_range_low=item.get("price_range_low",0),
                    price_range_high=item.get("price_range_high",0),
                    suitable_rooms=item.get("suitable_rooms",[]),
                )
                lib.catalog[item["id"]] = spec
                count += 1
    lib._build_index()
    print(f"Furniture library expanded: +{count} items, total {len(lib.catalog)}")
    return count

print("furniture_extra v1 ready")
