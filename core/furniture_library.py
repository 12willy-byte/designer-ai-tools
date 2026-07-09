import json
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class FurnitureSpec:
    id: str; name: str; name_en: str=''; category: str=''; subcategory: str=''
    width_mm: int=600; depth_mm: int=600; height_mm: int=600
    seat_height_mm: int=0; mattress_size: str=''; capacity: int=1
    door_opening: bool=False; clearance_front_mm: int=600
    clearance_back_mm: int=0; clearance_sides_mm: int=100
    material_type: str='wood'; styles: list=field(default_factory=lambda:['modern'])
    color_tags: list=field(default_factory=lambda:['neutral'])
    model_path: str=''; model_source: str='builtin'; model_url: str=''
    price_range_low: float=0; price_range_high: float=0
    suitable_rooms: list=field(default_factory=lambda:['living','bedroom','dining'])

CATALOG = [
    FurnitureSpec(id='sofa-3seat',name='三人沙发',category='sofa',width_mm=2200,depth_mm=900,height_mm=850,seat_height_mm=420,capacity=3,clearance_front_mm=800,material_type='fabric',styles=['modern','minimalist'],price_range_low=2000,price_range_high=8000,suitable_rooms=['living']),
    FurnitureSpec(id='sofa-2seat',name='双人沙发',category='sofa',width_mm=1600,depth_mm=850,height_mm=820,capacity=2,clearance_front_mm=700,material_type='fabric',styles=['modern'],price_range_low=1500,price_range_high=5000,suitable_rooms=['living','bedroom']),
    FurnitureSpec(id='sofa-lshape',name='L型转角沙发',category='sofa',subcategory='l-shape',width_mm=3000,depth_mm=1700,height_mm=850,capacity=5,clearance_front_mm=900,material_type='fabric',styles=['modern','contemporary'],price_range_low=3500,price_range_high=12000,suitable_rooms=['living']),
    FurnitureSpec(id='bed-double-180',name='双人床 1.8m',category='bed',subcategory='king',width_mm=1900,depth_mm=2200,height_mm=1050,mattress_size='1.8m',capacity=2,clearance_front_mm=700,clearance_sides_mm=550,material_type='wood',styles=['modern','luxury'],color_tags=['walnut'],price_range_low=2500,price_range_high=10000,suitable_rooms=['bedroom']),
    FurnitureSpec(id='bed-double-150',name='双人床 1.5m',category='bed',subcategory='double',width_mm=1600,depth_mm=2100,height_mm=1000,mattress_size='1.5m',capacity=2,clearance_front_mm=700,clearance_sides_mm=500,material_type='wood',styles=['modern','minimalist','japanese'],price_range_low=1500,price_range_high=6000,suitable_rooms=['bedroom']),
    FurnitureSpec(id='bed-single',name='单人床',category='bed',subcategory='single',width_mm=1000,depth_mm=2000,height_mm=900,mattress_size='0.9m',capacity=1,clearance_front_mm=600,clearance_sides_mm=400,material_type='wood',styles=['modern'],price_range_low=800,price_range_high=3000,suitable_rooms=['bedroom','study']),
    FurnitureSpec(id='table-dining-4',name='餐桌 4人',category='table',subcategory='dining',width_mm=1400,depth_mm=800,height_mm=750,capacity=4,clearance_front_mm=900,material_type='wood',styles=['modern','minimalist','scandinavian'],price_range_low=800,price_range_high=3000,suitable_rooms=['dining']),
    FurnitureSpec(id='table-dining-6',name='餐桌 6人',category='table',subcategory='dining',width_mm=1800,depth_mm=900,height_mm=760,capacity=6,clearance_front_mm=1000,material_type='wood',styles=['modern','contemporary'],price_range_low=1500,price_range_high=5000,suitable_rooms=['dining']),
    FurnitureSpec(id='table-coffee',name='茶几',category='table',subcategory='coffee',width_mm=1200,depth_mm=600,height_mm=420,clearance_front_mm=500,material_type='wood',styles=['modern','minimalist'],price_range_low=500,price_range_high=2500,suitable_rooms=['living']),
    FurnitureSpec(id='chair-dining',name='餐椅',category='chair',subcategory='dining',width_mm=480,depth_mm=520,height_mm=850,seat_height_mm=450,capacity=1,clearance_front_mm=500,material_type='wood',styles=['modern','minimalist'],price_range_low=200,price_range_high=800,suitable_rooms=['dining']),
    FurnitureSpec(id='chair-desk',name='书桌椅',category='chair',subcategory='desk',width_mm=550,depth_mm=580,height_mm=950,seat_height_mm=460,capacity=1,clearance_front_mm=600,material_type='fabric',styles=['modern','ergonomic'],price_range_low=300,price_range_high=1500,suitable_rooms=['study']),
    FurnitureSpec(id='cabinet-tv',name='电视柜',category='cabinet',subcategory='tv-stand',width_mm=2000,depth_mm=400,height_mm=450,clearance_front_mm=700,material_type='wood',styles=['modern','minimalist'],price_range_low=800,price_range_high=3000,suitable_rooms=['living']),
    FurnitureSpec(id='cabinet-wardrobe-2door',name='双门衣柜',category='cabinet',subcategory='wardrobe',width_mm=1200,depth_mm=600,height_mm=2200,door_opening=True,clearance_front_mm=700,material_type='wood',styles=['modern','minimalist'],price_range_low=1500,price_range_high=5000,suitable_rooms=['bedroom']),
    FurnitureSpec(id='cabinet-wardrobe-3door',name='三门衣柜',category='cabinet',subcategory='wardrobe',width_mm=1800,depth_mm=600,height_mm=2200,door_opening=True,clearance_front_mm=700,material_type='wood',styles=['modern','luxury'],price_range_low=2500,price_range_high=8000,suitable_rooms=['bedroom']),
    FurnitureSpec(id='cabinet-shoe',name='鞋柜',category='cabinet',subcategory='shoe',width_mm=800,depth_mm=350,height_mm=1100,clearance_front_mm=500,material_type='wood',styles=['modern'],price_range_low=400,price_range_high=1500,suitable_rooms=['entry']),
    FurnitureSpec(id='desk-standard',name='书桌',category='table',subcategory='desk',width_mm=1200,depth_mm=600,height_mm=750,clearance_front_mm=700,material_type='wood',styles=['modern','minimalist'],price_range_low=500,price_range_high=2000,suitable_rooms=['study','bedroom']),
    FurnitureSpec(id='light-pendant',name='吊灯',category='lighting',subcategory='pendant',width_mm=600,depth_mm=600,height_mm=400,material_type='metal',styles=['modern','luxury'],price_range_low=300,price_range_high=2000,suitable_rooms=['dining','living']),
    FurnitureSpec(id='light-floor',name='落地灯',category='lighting',subcategory='floor',width_mm=300,depth_mm=300,height_mm=1600,material_type='metal',styles=['modern','minimalist'],price_range_low=200,price_range_high=1000,suitable_rooms=['living','bedroom']),
    FurnitureSpec(id='decor-rug-200',name='地毯 2m×3m',category='decor',subcategory='rug',width_mm=2000,depth_mm=3000,height_mm=10,material_type='fabric',styles=['modern','scandinavian'],price_range_low=300,price_range_high=1500,suitable_rooms=['living']),
    FurnitureSpec(id='decor-plant',name='大型绿植',category='decor',subcategory='plant',width_mm=400,depth_mm=400,height_mm=1500,material_type='composite',styles=['modern','natural'],price_range_low=100,price_range_high=500,suitable_rooms=['living','entry','balcony']),
    FurnitureSpec(id='cabinet-kitchen-base',name='橱柜地柜',category='cabinet',subcategory='kitchen-base',width_mm=600,depth_mm=600,height_mm=850,clearance_front_mm=900,material_type='wood',styles=['modern'],price_range_low=500,price_range_high=1800,suitable_rooms=['kitchen']),
    FurnitureSpec(id='fixture-toilet',name='马桶',category='fixture',subcategory='toilet',width_mm=400,depth_mm=700,height_mm=750,clearance_front_mm=600,clearance_sides_mm=200,material_type='composite',styles=['modern'],price_range_low=800,price_range_high=3000,suitable_rooms=['bathroom']),
    FurnitureSpec(id='fixture-vanity',name='浴室柜',category='cabinet',subcategory='vanity',width_mm=800,depth_mm=500,height_mm=850,clearance_front_mm=600,material_type='wood',styles=['modern'],price_range_low=800,price_range_high=3000,suitable_rooms=['bathroom']),
]

class FurnitureLibrary:
    def __init__(self): self.catalog = {f.id: f for f in CATALOG}; self._build_index()
    def _build_index(self):
        self.by_category = {}; self.by_room = {}
        for f in self.catalog.values():
            self.by_category.setdefault(f.category, []).append(f)
            for room in f.suitable_rooms: self.by_room.setdefault(room, []).append(f)
    def get(self, fid): return self.catalog.get(fid)
    def search(self, category=None, room=None, style=None, keyword=None):
        r = list(self.catalog.values())
        if category: r = [f for f in r if f.category == category]
        if room: r = [f for f in r if room in f.suitable_rooms]
        if style: r = [f for f in r if style in f.styles]
        if keyword:
            kw = keyword.lower(); r = [f for f in r if kw in f.name.lower() or kw in f.name_en.lower()]
        return r
    def get_room_defaults(self, rt):
        defaults = {
            'living': ['sofa-3seat','table-coffee','cabinet-tv','light-floor','decor-rug-200'],
            'bedroom': ['bed-double-180','cabinet-wardrobe-3door','light-floor'],
            'dining': ['table-dining-4','chair-dining','chair-dining','chair-dining','chair-dining','light-pendant'],
            'study': ['desk-standard','chair-desk'],
            'kitchen': ['cabinet-kitchen-base','cabinet-kitchen-base'],
            'bathroom': ['fixture-toilet','fixture-vanity'],
            'entry': ['cabinet-shoe','decor-plant'],
        }
        return [self.catalog[fid] for fid in defaults.get(rt, []) if fid in self.catalog]
    def export_catalog(self, path):
        data = [{k:v for k,v in f.__dict__.items()} for f in self.catalog.values()]
        json.dump(data, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2, default=str)

_lib = None
def get_library():
    global _lib
    if _lib is None: _lib = FurnitureLibrary()
    return _lib
