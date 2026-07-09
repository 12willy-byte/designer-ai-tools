"""
统一数据模型 - 项目中所有模块共享的数据结构
注意: 房间的几何数据(Room/Wall/Furniture)统一在 core/scene3d.py 中定义，
      此处只保留设计条件(非几何信息)。
"""
from dataclasses import dataclass, field


@dataclass
class ProjectInfo:
    name: str = ""
    address: str = ""
    house_type: str = ""
    area_m2: float = 0
    design_type: str = ""
    expected_completion: str = ""
    designer: str = ""

@dataclass
class FamilyInfo:
    residents: str = ""
    composition: str = ""
    children_ages: str = ""
    elderly: str = ""
    pets: str = ""
    work_from_home: str = ""
    entertain_frequency: str = ""
    cooking_frequency: str = ""
    dining_habit: str = ""
    movement_preference: str = ""
    storage_need: str = ""
    hobbies: str = ""

@dataclass
class StylePreference:
    primary_style: str = ""
    color_tone: str = ""
    keywords: str = ""
    floor_material: str = ""
    wall_material: str = ""
    ceiling_type: str = ""

@dataclass
class BudgetInfo:
    total_budget: float = 0
    hard_decoration: float = 0
    soft_decoration: float = 0
    appliances: float = 0
    notes: str = ""

@dataclass
class DesignConditions:
    """设计条件 — 不含几何尺寸，尺寸由 Scene3D 提供"""
    project: ProjectInfo = field(default_factory=ProjectInfo)
    family: FamilyInfo = field(default_factory=FamilyInfo)
    style: StylePreference = field(default_factory=StylePreference)
    rooms: list = field(default_factory=list)  # [{"name": str, "requirements": dict}, ...]
    budget: BudgetInfo = field(default_factory=BudgetInfo)
    special_requirements: dict = field(default_factory=dict)
    source_note: str = ""
