# -*- coding: utf-8 -*-
"""
electrical_plan - Electrical & MEP point layout generation
Generates: outlet positions, switch positions, lighting circuits, HVAC zones
Based on room function and GB standards.
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass
class ElectricalPoint:
    id: str
    room_name: str
    type: str  # outlet/switch/light/data/tv/ac/kitchen
    position_mm: list
    height_mm: int
    spec: str  # 10A/16A/USB/etc
    circuit: str
    note: str = ""

@dataclass
class ElectricalPlan:
    points: list
    circuits: dict
    total_load_w: float
    main_breaker_a: int

ROOM_ELECTRICAL_RULES = {
    "客厅": {
        "outlets": [
            {"type": "outlet", "count": 3, "height": 300, "spec": "10A 五孔", "spacing": "evenly"},
            {"type": "outlet", "count": 1, "height": 300, "spec": "16A 三孔", "note": "空调专用"},
            {"type": "tv", "count": 1, "height": 300, "spec": "TV+网络+电源"},
        ],
        "switches": [{"type": "switch", "count": 2, "height": 1300, "spec": "双控"}],
        "lights": [{"type": "light", "count": 4, "spec": "LED 12W", "circuit": "照明回路"}],
        "special": [{"type": "ac", "count": 1, "spec": "16A 插座", "height": 2200, "circuit": "空调回路"}],
    },
    "主卧": {
        "outlets": [
            {"type": "outlet", "count": 2, "height": 300, "spec": "10A 五孔"},
            {"type": "outlet", "count": 2, "height": 700, "spec": "10A+USB", "note": "床头"},
            {"type": "outlet", "count": 1, "height": 300, "spec": "16A 三孔", "note": "空调"},
            {"type": "tv", "count": 1, "height": 300, "spec": "TV+网络"},
        ],
        "switches": [{"type": "switch", "count": 2, "height": 1300, "spec": "双控"}],
        "lights": [{"type": "light", "count": 2, "spec": "LED 12W"}],
        "special": [{"type": "ac", "count": 1, "spec": "16A", "height": 2200, "circuit": "空调回路"}],
    },
    "厨房": {
        "outlets": [
            {"type": "outlet", "count": 4, "height": 1200, "spec": "10A 五孔带开关", "note": "台面以上"},
            {"type": "outlet", "count": 1, "height": 300, "spec": "16A 三孔", "note": "冰箱"},
            {"type": "outlet", "count": 1, "height": 2200, "spec": "10A", "note": "油烟机"},
            {"type": "outlet", "count": 1, "height": 300, "spec": "10A", "note": "洗碗机/消毒柜"},
        ],
        "switches": [{"type": "switch", "count": 1, "height": 1300, "spec": "单控"}],
        "lights": [{"type": "light", "count": 2, "spec": "LED 12W 防水"}],
        "special": [
            {"type": "kitchen", "count": 1, "spec": "4mm2 独立回路", "circuit": "厨房回路"},
        ],
    },
    "卫生间": {
        "outlets": [
            {"type": "outlet", "count": 1, "height": 1300, "spec": "10A 防水盖", "note": "吹风机"},
            {"type": "outlet", "count": 1, "height": 300, "spec": "10A 防水盖", "note": "智能马桶"},
        ],
        "switches": [{"type": "switch", "count": 1, "height": 1300, "spec": "防水"}],
        "lights": [{"type": "light", "count": 1, "spec": "LED 12W 防水"}],
        "special": [
            {"type": "bathroom", "count": 1, "spec": "4mm2 独立回路+漏保", "circuit": "卫生间回路"},
            {"type": "outlet", "count": 1, "height": 2200, "spec": "10A", "note": "热水器"},
        ],
    },
    "餐厅": {
        "outlets": [
            {"type": "outlet", "count": 2, "height": 300, "spec": "10A 五孔"},
            {"type": "outlet", "count": 1, "height": 1200, "spec": "10A", "note": "餐桌旁火锅/电磁炉"},
        ],
        "switches": [{"type": "switch", "count": 1, "height": 1300, "spec": "单控"}],
        "lights": [{"type": "light", "count": 2, "spec": "LED 12W 暖光"}],
    },
    "书房": {
        "outlets": [
            {"type": "outlet", "count": 3, "height": 300, "spec": "10A 五孔"},
            {"type": "outlet", "count": 2, "height": 700, "spec": "10A+USB", "note": "桌面"},
            {"type": "data", "count": 1, "height": 300, "spec": "网络口"},
        ],
        "switches": [{"type": "switch", "count": 1, "height": 1300, "spec": "单控"}],
        "lights": [{"type": "light", "count": 2, "spec": "LED 12W 4000K"}],
    },
}

def generate_electrical_plan(scene) -> ElectricalPlan:
    """Generate electrical point layout from Scene3D."""
    rooms = [_norm(r) for r in (get_rooms(scene))]
    
    all_points = []
    circuits = {
        "照明回路": {"breaker": "16A", "wire": "2.5mm2", "max_load_w": 3000},
        "普通插座回路1": {"breaker": "16A", "wire": "2.5mm2", "max_load_w": 3000},
        "普通插座回路2": {"breaker": "16A", "wire": "2.5mm2", "max_load_w": 3000},
        "厨房回路": {"breaker": "20A", "wire": "4mm2", "max_load_w": 4000},
        "卫生间回路": {"breaker": "20A", "wire": "4mm2", "max_load_w": 4000},
        "空调回路1": {"breaker": "20A", "wire": "4mm2", "max_load_w": 4000},
        "空调回路2": {"breaker": "20A", "wire": "4mm2", "max_load_w": 4000},
    }
    
    point_id = 0
    point_circuit_map = {"outlet": "普通插座回路1", "switch": "照明回路", "light": "照明回路",
                         "tv": "普通插座回路1", "data": "普通插座回路1"}
    
    for room in rooms:
        rt = room.get('type', '客厅')
        rname = room.get('name', '')
        rl = room.get('length_mm', 4000)
        rw = room.get('width_mm', 3500)
        
        rules = ROOM_ELECTRICAL_RULES.get(rt, ROOM_ELECTRICAL_RULES["客厅"])
        
        for cat in ['outlets', 'switches', 'lights', 'special']:
            for rule in rules.get(cat, []):
                count = rule.get('count', 1)
                for i in range(count):
                    # Distribute points along the room
                    if rule.get('spacing') == 'evenly':
                        x = rl * (i + 1) / (count + 1)
                        z = rw * 0.5
                    else:
                        x = rl * (0.25 + i * 0.5 / max(count, 1))
                        z = rw * (0.3 + (i % 2) * 0.4)
                    
                    point_id += 1
                    circuit = rule.get('circuit', point_circuit_map.get(rule['type'], '照明回路'))
                    
                    all_points.append(ElectricalPoint(
                        id=f"EP{point_id:03d}",
                        room_name=rname,
                        type=rule['type'],
                        position_mm=[round(x), 0, round(z)],
                        height_mm=rule.get('height', 300),
                        spec=rule.get('spec', '10A'),
                        circuit=circuit,
                        note=rule.get('note', ''),
                    ))
    
    # Calculate total load
    total_w = 0
    for p in all_points:
        if '回路' in p.circuit or p.type == 'ac':
            total_w += 2000  # AC/kitchen circuit
        elif p.type in ('light', 'switch'):
            total_w += 12  # LED per light
        else:
            total_w += 100  # General outlet
    
    main_breaker = max(40, int(total_w / 220 * 1.5 / 5) * 5 + 5)
    
    return ElectricalPlan(
        points=all_points,
        circuits=circuits,
        total_load_w=round(total_w),
        main_breaker_a=main_breaker,
    )

def print_electrical_plan(plan: ElectricalPlan):
    """Pretty-print electrical plan."""
    lines = [
        "=" * 60,
        f"  ELECTRICAL PLAN",
        f"  Total Points: {len(plan.points)} | Load: {plan.total_load_w}W | Main: {plan.main_breaker_a}A",
        "=" * 60,
    ]
    
    by_room = {}
    for p in plan.points:
        by_room.setdefault(p.room_name, []).append(p)
    
    for room, pts in by_room.items():
        lines.append(f"\n  {room}:")
        by_type = {}
        for p in pts:
            by_type.setdefault(p.type, []).append(p)
        for t, plist in by_type.items():
            specs = set(p.spec for p in plist)
            lines.append(f"    {t}: {len(plist)}x [{', '.join(specs)}]")
            for p in plist:
                lines.append(f"      [{p.id}] {p.spec} @ H={p.height_mm}mm {p.note} | Circuit: {p.circuit}")
    
    lines.append(f"\n  CIRCUITS:")
    for name, spec in plan.circuits.items():
        used = sum(1 for p in plan.points if p.circuit == name)
        if used > 0:
            lines.append(f"    {name}: {spec['breaker']} / {spec['wire']} / {used} points")
    
    lines.append("=" * 60)
    text = "\n".join(lines)
    print(text)
    return text

from core.scene_utils import normalize as _n, get_rooms, get_walls, get_doors, get_windows
_norm = _n  # alias for modules that use _norm