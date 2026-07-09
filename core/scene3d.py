"""
3D 场景引擎 - 整个项目的唯一数据源
所有产物(平面图/效果图/施工图/预算)都从 3D 场景派生

数据结构设计原则:
1. 每个元素有唯一 ID (uuid)
2. 所有坐标在统一世界坐标系 (右手: X=右, Y=上, Z=前, 单位=mm)
3. 墙体定义其上表面中心线,厚度垂直于线方向
4. 开口(门窗)偏移量从墙起点沿墙方向计算
"""
import uuid, math, json, os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ============================================================
# 基础类型
# ============================================================

@dataclass
class Point3D:
    x: float = 0; y: float = 0; z: float = 0
    def __iter__(self): return iter((self.x, self.y, self.z))
    def __add__(self, other): return Point3D(self.x+other.x, self.y+other.y, self.z+other.z)
    def __sub__(self, other): return Point3D(self.x-other.x, self.y-other.y, self.z-other.z)
    def length(self): return math.hypot(self.x, self.y, self.z)

@dataclass
class Point2D:
    x: float = 0; y: float = 0

class OpeningType(Enum):
    DOOR = "door"
    WINDOW = "window"


# ============================================================
# 场景元素
# ============================================================

@dataclass
class Opening:
    """墙体上的开口(门/窗)"""
    id: str
    type: OpeningType
    offset_mm: float         # 从墙起点沿墙方向的偏移(mm)
    width_mm: float          # 开口宽度
    height_mm: float         # 开口高度
    sill_height_mm: float = 0  # 窗台高度(门为0)
    swing: str = ""          # 门开启方向 left/right (窗为空)

@dataclass
class Wall:
    """墙体 (沿上表面中心线定义)"""
    id: str
    start: Point3D           # 起点
    end: Point3D             # 终点
    height_mm: float = 2800  # 高度
    thickness_mm: float = 120 # 厚度
    openings: list = field(default_factory=list)  # [Opening]
    is_load_bearing: bool = False
    room_id: str = ""

    @property
    def length_mm(self):
        dx = self.end.x - self.start.x
        dz = self.end.z - self.start.z
        return math.hypot(dx, dz)

    @property
    def direction(self):
        """墙的方向向量 (归一化)"""
        dx = self.end.x - self.start.x
        dz = self.end.z - self.start.z
        length = self.length_mm or 1
        return (dx/length, dz/length)

    @property
    def normal(self):
        """墙的法向量"""
        dx, dz = self.direction
        return (-dz, dx)

    def opening_segments(self):
        """返回实心墙段 [(start_offset, end_offset), ...]"""
        opens = sorted(self.openings, key=lambda o: o.offset_mm)
        segments = []
        prev = 0
        for op in opens:
            if op.offset_mm > prev + 5:
                segments.append((prev, op.offset_mm))
            prev = op.offset_mm + op.width_mm
        if prev < self.length_mm - 5:
            segments.append((prev, self.length_mm))
        return segments

    @property
    def solid_area_m2(self):
        """墙体实心部分面积 (m2)"""
        area = 0
        for s, e in self.opening_segments():
            area += (e - s) * self.height_mm / 1e6
        return area


@dataclass
class Room:
    """房间 — 3D 场景中的几何房间"""
    id: str
    name: str
    type: str = ""  # room function
    wall_ids: list = field(default_factory=list)
    floor_points: list = field(default_factory=list)  # [Point3D] 地面轮廓
    ceiling_height_mm: float = 2800
    requirements: dict = field(default_factory=dict)   # 设计需求

    @property
    def area_m2(self):
        if len(self.floor_points) < 3: return 0
        pts = [(p.x, p.z) for p in self.floor_points]
        area = 0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i+1)%n]
            area += x1*y2 - x2*y1
        return abs(area) / 2e6

    @property
    def perimeter_mm(self):
        if len(self.floor_points) < 3: return 0
        p = 0
        pts = [(p.x, p.z) for p in self.floor_points]
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i+1)%n]
            p += math.hypot(x2-x1, y2-y1)
        return p


@dataclass
class Furniture:
    """家具"""
    id: str
    name: str
    category: str           # sofa/table/bed/cabinet/chair
    position: Point3D
    rotation_deg: float = 0
    width_mm: float = 0
    depth_mm: float = 0
    height_mm: float = 0
    room_id: str = ""
    model_path: str = ""    # 外部3D模型路径


@dataclass
class Beam:
    id: str
    position: Point3D
    width_mm: float
    depth_mm: float
    length_mm: float

@dataclass
class Column:
    id: str
    position: Point3D
    width_mm: float
    depth_mm: float
    height_mm: float = 2800


# ============================================================
# 场景
# ============================================================

class Scene3D:
    """全房 3D 场景 - 唯一数据源"""
    
    def __init__(self, name: str = ""):
        self.name = name
        self.walls: dict[str, Wall] = {}
        self.rooms: dict[str, Room] = {}
        self.doors: dict[str, Opening] = {}
        self.windows: dict[str, Opening] = {}
        self.furniture: dict[str, Furniture] = {}
        self.beams: dict[str, Beam] = {}
        self.columns: dict[str, Column] = {}
        self.design_conditions: Optional[dict] = None  # 设计需求(非几何)

    # ── 设计条件绑定 ──

    def apply_design_conditions(self, conditions) -> "Scene3D":
        """
        将 DesignConditions 中的需求绑定到场景房间上。
        通过房间名称匹配。
        """
        import core.data_model as dm
        if isinstance(conditions, dm.DesignConditions):
            cond_rooms = conditions.rooms  # [{"name": ..., "requirements": ...}]
            self.design_conditions = {
                "project": conditions.project.__dict__,
                "family": conditions.family.__dict__,
                "style": conditions.style.__dict__,
                "budget": conditions.budget.__dict__,
                "special": conditions.special_requirements,
                "rooms": cond_rooms,
            }
        elif isinstance(conditions, dict):
            cond_rooms = conditions.get("rooms", [])
            self.design_conditions = conditions
        else:
            return self

        # 按名称匹配
        for cr in cond_rooms:
            cr_name = cr.get("name", "") if isinstance(cr, dict) else cr.name
            for room in self.rooms.values():
                if room.name == cr_name:
                    room.requirements = cr.get("requirements", {}) if isinstance(cr, dict) else cr.requirements
                    break
        return self

    @property
    def style(self) -> dict:
        """获取风格偏好"""
        if self.design_conditions:
            return self.design_conditions.get("style", {})
        return {}

    @property
    def family(self) -> dict:
        """获取家庭信息"""
        if self.design_conditions:
            return self.design_conditions.get("family", {})
        return {}

    # ── 构建方法 ──

    @classmethod
    def from_roomplan(cls, data_or_path) -> "Scene3D":
        """从 RoomPlan JSON 构建场景"""
        if isinstance(data_or_path, str):
            with open(data_or_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = data_or_path

        surfaces = data.get("surfaces", [])
        smap = {s["identifier"]: s for s in surfaces}

        def tform_point(m, x, y, z):
            return Point3D(
                m[0]*x + m[4]*y + m[8]*z + m[12],
                m[1]*x + m[5]*y + m[9]*z + m[13],
                m[2]*x + m[6]*y + m[10]*z + m[14]
            )

        scene = cls(name=data.get("name", os.path.basename(data_or_path) if isinstance(data_or_path, str) else ""))

        # 墙
        for s in surfaces:
            if s["category"] != "wall":
                continue
            m = s["transform"]
            length = s["dimensions"]["x"]
            p1 = tform_point(m, 0, 0, 0)
            p2 = tform_point(m, length, 0, 0)
            wall = Wall(
                id=s["identifier"],
                start=p1, end=p2,
                height_mm=s["dimensions"].get("y", 2800),
                thickness_mm=120,
            )
            scene.walls[wall.id] = wall

        # 门窗
        for s in surfaces:
            if s["category"] not in ("door", "window"):
                continue
            pid = s.get("parentIdentifier")
            if pid and pid in scene.walls:
                wall = scene.walls[pid]
                m = s["transform"]
                pos = tform_point(m, 0, 0, 0)
                dx, dz = wall.direction
                wx = dx; wz = dz
                offset = (pos.x - wall.start.x) * wx + (pos.z - wall.start.z) * wz
                typ = OpeningType.DOOR if s["category"] == "door" else OpeningType.WINDOW
                op = Opening(
                    id=s["identifier"],
                    type=typ,
                    offset_mm=round(max(0, offset), 1),
                    width_mm=s["dimensions"]["x"],
                    height_mm=s["dimensions"]["y"],
                    sill_height_mm=round(pos.y, 1) if typ == OpeningType.WINDOW else 0,
                )
                wall.openings.append(op)
                if typ == OpeningType.DOOR:
                    scene.doors[op.id] = op
                else:
                    scene.windows[op.id] = op

        # 房间
        for rm in data.get("rooms", []):
            rid = rm.get("identifier", str(uuid.uuid4())[:8])
            name = rm.get("displayName", "")
            room_wall_ids = [s for s in rm.get("surfaces", []) if s in scene.walls]
            floor_pts = scene._build_floor_polygon(room_wall_ids)
            room = Room(
                id=rid, name=name,
                wall_ids=room_wall_ids,
                floor_points=floor_pts,
            )
            scene.rooms[rid] = room

        # 梁柱
        for s in surfaces:
            m = s.get("transform")
            if not m:
                continue
            p = tform_point(m, 0, 0, 0)
            if s["category"] == "beam":
                beam = Beam(id=s["identifier"], position=p,
                           width_mm=s["dimensions"]["x"],
                           depth_mm=s["dimensions"]["y"],
                           length_mm=s["dimensions"].get("length", s["dimensions"]["x"]))
                scene.beams[beam.id] = beam
            elif s["category"] == "column":
                col = Column(id=s["identifier"], position=p,
                            width_mm=s["dimensions"]["x"],
                            depth_mm=s["dimensions"]["y"])
                scene.columns[col.id] = col

        return scene

    def _build_floor_polygon(self, wall_ids: list) -> list:
        """从墙ID列表构建地面多边形 (凸包+排序)"""
        if len(wall_ids) < 3:
            return []
        all_pts = []
        for wid in wall_ids:
            w = self.walls.get(wid)
            if w:
                all_pts.append((round(w.start.x), round(w.start.z)))
                all_pts.append((round(w.end.x), round(w.end.z)))
        unique = list(dict.fromkeys(all_pts))
        if len(unique) < 3:
            return []
        cx = sum(p[0] for p in unique) / len(unique)
        cz = sum(p[1] for p in unique) / len(unique)
        unique.sort(key=lambda p: math.atan2(p[1]-cz, p[0]-cx))
        return [Point3D(x=p[0], y=0, z=p[1]) for p in unique]

    @classmethod
    def from_cad(cls, dxf_path: str) -> "Scene3D":
        """从 CAD DXF 构建场景（含拓扑分析识别房间）"""
        from core.cad_reader import read_dxf_with_rooms
        data = read_dxf_with_rooms(dxf_path)
        scene = cls(name=os.path.basename(dxf_path))
        for i, (x1, y1, x2, y2, t) in enumerate(data["walls"]):
            wid = f"wall-{i}"
            scene.walls[wid] = Wall(id=wid, start=Point3D(x=x1, y=0, z=y1),
                                    end=Point3D(x=x2, y=0, z=y2), thickness_mm=t)
        detected = data.get("detected_rooms", [])
        if detected:
            for i, droom in enumerate(detected):
                rid = f"room-cad-{i}"
                fpts = [Point3D(x=p["x"], y=0, z=p["y"]) for p in droom["floor_points"]]
                room = Room(id=rid, name=droom.get("name", f"房间{i+1}"), floor_points=fpts)
                for wid, w in scene.walls.items():
                    cx = (w.start.x + w.end.x) / 2
                    cz = (w.start.z + w.end.z) / 2
                    mx = min(p.x for p in fpts) - 500
                    Mx = max(p.x for p in fpts) + 500
                    mz = min(p.z for p in fpts) - 500
                    Mz = max(p.z for p in fpts) + 500
                    if mx <= cx <= Mx and mz <= cz <= Mz:
                        room.wall_ids.append(wid)
                scene.rooms[rid] = room
        else:
            texts = data.get("texts", [])
            for t in texts:
                name = t.get("text", "")
                if name and len(name) < 20:
                    rid = f"room-{len(scene.rooms)}"
                    nw = []
                    tx, ty = t.get("x", 0), t.get("y", 0)
                    for wid, w in scene.walls.items():
                        cx = (w.start.x + w.end.x) / 2
                        cz = (w.start.z + w.end.z) / 2
                        if abs(cx - tx) < 5000 and abs(cz - ty) < 5000:
                            nw.append(wid)
                    room = Room(id=rid, name=name, wall_ids=nw, floor_points=scene._build_floor_polygon(nw))
                    scene.rooms[rid] = room
        return scene
        """从 CAD DXF 构建场景"""
        from core.cad_reader import read_dxf_floor_plan
        data = read_dxf_floor_plan(dxf_path)
        scene = cls(name=os.path.basename(dxf_path))
        
        for i, (x1, y1, x2, y2, t) in enumerate(data["walls"]):
            wid = f"wall-{i}"
            wall = Wall(
                id=wid,
                start=Point3D(x=x1, y=0, z=y1),
                end=Point3D(x=x2, y=0, z=y2),
                thickness_mm=t,
            )
            scene.walls[wid] = wall
        
        # 从文字标注推测房间
        texts = data.get("texts", [])
        for t in texts:
            name = t.get("text", "")
            if name and len(name) < 20:
                rid = f"room-{len(scene.rooms)}"
                # 找附近的墙
                nearby_walls = []
                tx, ty = t.get("x", 0), t.get("y", 0)
                for wid, w in scene.walls.items():
                    cx = (w.start.x + w.end.x) / 2
                    cz = (w.start.z + w.end.z) / 2
                    if abs(cx - tx) < 5000 and abs(cz - ty) < 5000:
                        nearby_walls.append(wid)
                floor_pts = scene._build_floor_polygon(nearby_walls)
                room = Room(id=rid, name=name, wall_ids=nearby_walls, floor_points=floor_pts)
                scene.rooms[rid] = room

        return scene

    @classmethod
    def from_json(cls, path: str) -> "Scene3D":
        """加载已序列化的场景 JSON"""
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        scene = cls(name=raw.get("name", ""))
        for w in raw.get("walls", []):
            wall = Wall(id=w["id"], start=Point3D(**w["start"]), end=Point3D(**w["end"]),
                       height_mm=w.get("height_mm", 2800), thickness_mm=w.get("thickness_mm", 120))
            for op in w.get("openings", []):
                wall.openings.append(Opening(id=op["id"], type=OpeningType(op["type"]),
                    offset_mm=op["offset_mm"], width_mm=op["width_mm"],
                    height_mm=op["height_mm"], sill_height_mm=op.get("sill_height_mm", 0)))
            scene.walls[wall.id] = wall
        for r in raw.get("rooms", []):
            room = Room(id=r["id"], name=r["name"], wall_ids=r.get("wall_ids", []),
                       ceiling_height_mm=r.get("ceiling_height_mm", 2800))
            room.floor_points = [Point3D(**p) for p in r.get("floor_points", [])]
            room.requirements = r.get("requirements", {})
            scene.rooms[room.id] = room
        for b in raw.get("beams", []):
            scene.beams[b["id"]] = Beam(id=b["id"], position=Point3D(**b["position"]),
                width_mm=b["width_mm"], depth_mm=b["depth_mm"], length_mm=b["length_mm"])
        for c in raw.get("columns", []):
            scene.columns[c["id"]] = Column(id=c["id"], position=Point3D(**c["position"]),
                width_mm=c["width_mm"], depth_mm=c["depth_mm"])
        for f in raw.get("furniture", []):
            scene.furniture[f["id"]] = Furniture(id=f["id"], name=f["name"], category=f["category"],
                position=Point3D(**f["position"]), rotation_deg=f.get("rotation_deg", 0),
                width_mm=f["width_mm"], depth_mm=f["depth_mm"], height_mm=f["height_mm"],
                room_id=f.get("room_id", ""), model_path=f.get("model_path", ""))
        scene.design_conditions = raw.get("design_conditions")
        return scene

    def to_dict(self) -> dict:
        """序列化场景为可 JSON 存储的字典"""
        return {
            "name": self.name,
            "walls": [{
                "id": w.id, "start": {"x": w.start.x, "y": w.start.y, "z": w.start.z},
                "end": {"x": w.end.x, "y": w.end.y, "z": w.end.z},
                "height_mm": w.height_mm, "thickness_mm": w.thickness_mm,
                "openings": [{"id": o.id, "type": o.type.value, "offset_mm": o.offset_mm,
                    "width_mm": o.width_mm, "height_mm": o.height_mm,
                    "sill_height_mm": o.sill_height_mm, "swing": o.swing} for o in w.openings],
            } for w in self.walls.values()],
            "rooms": [{
                "id": r.id, "name": r.name, "wall_ids": r.wall_ids,
                "floor_points": [{"x": p.x, "y": p.y, "z": p.z} for p in r.floor_points],
                "ceiling_height_mm": r.ceiling_height_mm,
                "requirements": r.requirements,
            } for r in self.rooms.values()],
            "beams": [{"id": b.id, "position": {"x": b.position.x, "y": b.position.y, "z": b.position.z},
                "width_mm": b.width_mm, "depth_mm": b.depth_mm, "length_mm": b.length_mm} for b in self.beams.values()],
            "columns": [{"id": c.id, "position": {"x": c.position.x, "y": c.position.y, "z": c.position.z},
                "width_mm": c.width_mm, "depth_mm": c.depth_mm, "height_mm": c.height_mm} for c in self.columns.values()],
            "furniture": [{"id": f.id, "name": f.name, "category": f.category,
                "position": {"x": f.position.x, "y": f.position.y, "z": f.position.z},
                "rotation_deg": f.rotation_deg, "width_mm": f.width_mm, "depth_mm": f.depth_mm,
                "height_mm": f.height_mm, "room_id": f.room_id, "model_path": f.model_path} for f in self.furniture.values()],
            "design_conditions": self.design_conditions,
        }

    def save(self, path: str):
        """序列化场景到 JSON 文件"""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2, default=str)
        return path

    # ── 查询方法 ──

    @property
    def total_floor_area_m2(self):
        return sum(r.area_m2 for r in self.rooms.values())

    @property
    def total_wall_area_m2(self):
        return sum(w.solid_area_m2 for w in self.walls.values())

    @property
    def total_ceiling_area_m2(self):
        return self.total_floor_area_m2

    @property
    def total_perimeter_m(self):
        return sum(r.perimeter_mm for r in self.rooms.values()) / 1000

    @property
    def door_count(self):
        return len(self.doors)

    @property
    def window_count(self):
        return len(self.windows)

    @property
    def room_count(self):
        return len(self.rooms)

    @property
    def total_opening_area_m2(self):
        area = 0
        for op in list(self.doors.values()) + list(self.windows.values()):
            area += op.width_mm * op.height_mm / 1e6
        return area

    @property
    def bounds(self):
        """场景包围盒 ((min_x,min_z), (max_x,max_z))"""
        pts = []
        for w in self.walls.values():
            pts.extend([(w.start.x, w.start.z), (w.end.x, w.end.z)])
        if not pts: return ((0,0),(0,0))
        return (
            (min(p[0] for p in pts), min(p[1] for p in pts)),
            (max(p[0] for p in pts), max(p[1] for p in pts)),
        )

    @property
    def bounds_3d(self):
        """场景 3D 包围盒"""
        min_x = min_z = float("inf")
        max_x = max_z = float("-inf")
        max_y = 0
        for w in self.walls.values():
            min_x = min(min_x, w.start.x, w.end.x)
            max_x = max(max_x, w.start.x, w.end.x)
            min_z = min(min_z, w.start.z, w.end.z)
            max_z = max(max_z, w.start.z, w.end.z)
            max_y = max(max_y, w.height_mm)
        if min_x == float("inf"):
            return ((0,0,0),(0,0,0))
        return ((min_x, 0, min_z), (max_x, max_y, max_z))

    def get_room_by_name(self, name: str) -> Optional[Room]:
        for r in self.rooms.values():
            if r.name == name: return r
        return None

    def get_walls_for_room(self, room: Room) -> list:
        """获取房间的所有墙对象"""
        return [self.walls[wid] for wid in room.wall_ids if wid in self.walls]
