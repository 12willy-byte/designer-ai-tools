import json
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class MaterialSpec:
    id: str; name: str; category: str=''
    color_hex: str='#CCCCCC'; roughness: float=0.5; metallic: float=0.0
    textures: list=field(default_factory=list)
    price_per_m2: float=0; unit: str='m2'
    styles: list=field(default_factory=lambda:['modern'])
    supplier_url: str=''; description: str=''

FLOORING = [
    MaterialSpec(id='floor-oak-light',name='浅橡木地板',category='flooring',color_hex='#D4A574',roughness=0.6,price_per_m2=150,styles=['modern','scandinavian','minimalist'],description='实木复合, 910x127x15mm'),
    MaterialSpec(id='floor-oak-dark',name='深橡木地板',category='flooring',color_hex='#8B6914',roughness=0.6,price_per_m2=180,styles=['modern','luxury'],description='实木复合, 910x127x15mm'),
    MaterialSpec(id='floor-walnut',name='胡桃木地板',category='flooring',color_hex='#5C4033',roughness=0.5,price_per_m2=250,styles=['luxury','modern'],description='实木, 910x125x18mm'),
    MaterialSpec(id='floor-marble-white',name='白色大理石',category='flooring',color_hex='#F5F0E8',roughness=0.1,metallic=0.3,price_per_m2=350,styles=['luxury','modern'],description='大理石 600x600mm'),
    MaterialSpec(id='floor-tile-grey',name='灰色瓷砖',category='flooring',color_hex='#B0B0B0',roughness=0.3,price_per_m2=80,styles=['modern','minimalist','industrial'],description='釉面砖 600x600mm'),
    MaterialSpec(id='floor-tile-beige',name='米色瓷砖',category='flooring',color_hex='#E8DCC8',roughness=0.3,price_per_m2=70,styles=['modern','minimalist'],description='釉面砖 600x600mm'),
    MaterialSpec(id='floor-terrazzo',name='水磨石',category='flooring',color_hex='#D0C8B8',roughness=0.2,price_per_m2=120,styles=['modern','retro'],description='水磨石 600x600mm'),
]

WALL_MATERIALS = [
    MaterialSpec(id='wall-white',name='白色乳胶漆',category='wall',color_hex='#FFFFFF',roughness=0.9,price_per_m2=25,styles=['modern','minimalist','all'],description='多乐士/立邦'),
    MaterialSpec(id='wall-warm-grey',name='暖灰乳胶漆',category='wall',color_hex='#D5CFC7',roughness=0.9,price_per_m2=28,styles=['modern','minimalist'],description='多乐士/立邦'),
    MaterialSpec(id='wall-light-beige',name='浅米色乳胶漆',category='wall',color_hex='#F2E8D5',roughness=0.9,price_per_m2=25,styles=['modern','scandinavian'],description='多乐士/立邦'),
    MaterialSpec(id='wall-accent-dark',name='深色背景墙',category='wall',color_hex='#3A3A3A',roughness=0.8,price_per_m2=35,styles=['modern','luxury'],description='艺术漆/硅藻泥'),
    MaterialSpec(id='wall-wallpaper-linen',name='亚麻纹理壁纸',category='wall',color_hex='#E8E0D5',roughness=0.85,price_per_m2=80,styles=['modern','natural','japanese'],description='无纺布壁纸'),
]

CEILING = [
    MaterialSpec(id='ceiling-white',name='白色天花板',category='ceiling',color_hex='#FFFFFF',roughness=0.95,price_per_m2=20,styles=['all'],description='乳胶漆'),
    MaterialSpec(id='ceiling-wood',name='木饰面吊顶',category='ceiling',color_hex='#C4A882',roughness=0.6,price_per_m2=150,styles=['modern','japanese'],description='实木贴皮'),
]

COUNTERTOP = [
    MaterialSpec(id='counter-quartz-white',name='白色石英石',category='countertop',color_hex='#F8F6F2',roughness=0.2,metallic=0.1,price_per_m2=500,styles=['modern','minimalist'],description='石英石 15mm'),
    MaterialSpec(id='counter-marble-carrara',name='卡拉拉大理石',category='countertop',color_hex='#F0EDE8',roughness=0.15,metallic=0.2,price_per_m2=800,styles=['luxury'],description='天然大理石 20mm'),
    MaterialSpec(id='counter-granite-black',name='黑色花岗岩',category='countertop',color_hex='#2A2A2A',roughness=0.1,metallic=0.3,price_per_m2=400,styles=['modern','industrial'],description='花岗岩 20mm'),
]

CABINET_FINISH = [
    MaterialSpec(id='cabinet-white-matte',name='白色哑光',category='cabinet',color_hex='#F5F5F5',roughness=0.7,price_per_m2=200,styles=['modern','minimalist'],description='哑光烤漆'),
    MaterialSpec(id='cabinet-wood-veneer',name='木纹贴面',category='cabinet',color_hex='#B8956A',roughness=0.55,price_per_m2=250,styles=['modern','japanese','scandinavian'],description='实木贴皮'),
    MaterialSpec(id='cabinet-grey-highgloss',name='灰色高光',category='cabinet',color_hex='#A0A0A0',roughness=0.1,metallic=0.05,price_per_m2=220,styles=['modern','contemporary'],description='高光烤漆'),
]

ALL_MATERIALS = FLOORING + WALL_MATERIALS + CEILING + COUNTERTOP + CABINET_FINISH

class MaterialLibrary:
    def __init__(self):
        self.catalog = {m.id: m for m in ALL_MATERIALS}
        self._build_index()
    def _build_index(self):
        self.by_category = {}
        for m in self.catalog.values():
            self.by_category.setdefault(m.category, []).append(m)
    def get(self, mid): return self.catalog.get(mid)
    def search(self, category=None, style=None, max_price=None):
        r = list(self.catalog.values())
        if category: r = [m for m in r if m.category == category]
        if style: r = [m for m in r if style in m.styles or 'all' in m.styles]
        if max_price: r = [m for m in r if m.price_per_m2 <= max_price]
        return r
    def get_defaults_for_room(self, room_type):
        scheme = {
            'living': {'floor': 'floor-oak-light', 'wall': 'wall-warm-grey', 'ceiling': 'ceiling-white'},
            'bedroom': {'floor': 'floor-oak-dark', 'wall': 'wall-light-beige', 'ceiling': 'ceiling-white'},
            'dining': {'floor': 'floor-walnut', 'wall': 'wall-white', 'ceiling': 'ceiling-white'},
            'kitchen': {'floor': 'floor-tile-grey', 'wall': 'wall-white', 'ceiling': 'ceiling-white', 'counter': 'counter-quartz-white', 'cabinet': 'cabinet-white-matte'},
            'bathroom': {'floor': 'floor-tile-grey', 'wall': 'floor-tile-beige', 'ceiling': 'ceiling-white'},
            'study': {'floor': 'floor-oak-light', 'wall': 'wall-white', 'ceiling': 'ceiling-white'},
        }
        return {k: self.get(v) for k, v in scheme.get(room_type, {}).items() if self.get(v)}
    def export(self, path):
        data = [{k:v for k,v in m.__dict__.items()} for m in self.catalog.values()]
        json.dump(data, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2, default=str)

_mlib = None
def get_library():
    global _mlib
    if _mlib is None: _mlib = MaterialLibrary()
    return _mlib
