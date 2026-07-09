# -*- coding: utf-8 -*-
"""
smart_home - Smart home device planning
IoT device positions, automation zones, scene configurations.
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass
class SmartDevice:
    id: str; room: str; type: str; position_mm: list
    protocol: str; power: str; automation: str

@dataclass
class SmartHomePlan:
    devices: list; automations: list; total_devices: int
    protocols: dict; estimated_cost: float

ROOM_SMART = {
    "客厅":[("智能开关",3,"Zigbee","灯光场景"),("智能窗帘",1,"Zigbee","日出开启"),("人体传感器",1,"Zigbee","自动亮灯"),("智能音箱",1,"WiFi","语音控制"),("空调网关",1,"WiFi","温控")],
    "主卧":[("智能开关",2,"Zigbee","睡眠模式"),("智能窗帘",1,"Zigbee","定时"),("人体传感器",1,"Zigbee","夜灯"),("温湿度计",1,"Zigbee","空调联动")],
    "厨房":[("烟雾传感器",1,"Zigbee","报警推送"),("燃气传感器",1,"Zigbee","阀门联动"),("水浸传感器",1,"Zigbee","关阀")],
    "卫生间":[("人体传感器",1,"Zigbee","自动排风"),("水浸传感器",1,"Zigbee","报警")],
    "玄关":[("门磁传感器",1,"Zigbee","离家模式"),("人体传感器",1,"Zigbee","欢迎灯"),("智能门锁",1,"Zigbee","联动")],
}

DEVICE_COSTS = {"智能开关":120,"智能窗帘":800,"人体传感器":60,"智能音箱":300,"空调网关":200,"烟雾传感器":80,"燃气传感器":100,"水浸传感器":70,"门磁传感器":50,"智能门锁":1500,"温湿度计":50}

def generate_smart_home(scene) -> SmartHomePlan:
    rooms = [_n(r) for r in (getattr(scene,'rooms',[]) or [])]
    devices = []; did = 0
    protocols = {"Zigbee":0,"WiFi":0}
    
    for r in rooms:
        rt = r.get('type',''); nm = r.get('name','')
        rl = r.get('length_mm',4000); rw = r.get('width_mm',3500)
        
        rules = ROOM_SMART.get(rt, [])
        for dtype, count, proto, auto in rules:
            for _ in range(count):
                did += 1
                x = rl * (0.2 + _ * 0.3)
                z = rw * (0.3 + (_%2) * 0.4)
                devices.append(SmartDevice(f"D{did:03d}", nm, dtype, [int(x),1500,int(z)], proto, "电池" if proto=="Zigbee" else "220V", auto))
                protocols[proto] = protocols.get(proto,0) + 1
    
    automations = ["离家模式: 关灯+关窗帘+设防","回家模式: 开灯+开窗帘+撤防","睡眠模式: 关灯+关窗帘+夜灯","观影模式: 关主灯+关窗帘+氛围灯"]
    
    total_cost = sum(DEVICE_COSTS.get(d.type,100) for d in devices)
    
    return SmartHomePlan(devices, automations, len(devices), protocols, total_cost)

def print_smart_home(plan):
    lines=["="*60,f"SMART HOME: {plan.total_devices} devices | Cost: {plan.estimated_cost:,}","="*60]
    by_room = {}
    for d in plan.devices:
        by_room.setdefault(d.room, []).append(d)
    for room, devs in by_room.items():
        lines.append(f"\n  {room}:")
        for d in devs:
            lines.append(f"    [{d.id}] {d.type} ({d.protocol}) - {d.automation}")
    lines.append(f"\nProtocols: {plan.protocols}")
    lines.append(f"\nAutomations:")
    for a in plan.automations: lines.append(f"  - {a}")
    lines.append(f"\nGateway: 1x Zigbee网关 (约300)")
    lines.append(f"Total: {plan.estimated_cost+300:,}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t

from core.scene_utils import normalize as _n