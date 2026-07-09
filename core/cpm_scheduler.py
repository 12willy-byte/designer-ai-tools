# -*- coding: utf-8 -*-
"""
cpm_scheduler - Critical Path Method construction scheduling
Task dependencies, duration estimation, critical path, milestone tracking.
"""
import json, os, math, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

@dataclass
class Task:
    id: str; name: str; duration_days: int
    dependencies: list; workers: int; cost_estimate: float
    early_start: int = 0; early_finish: int = 0; is_critical: bool = False

@dataclass
class Schedule:
    tasks: list; total_days: int; critical_path: list
    total_cost: float; milestones: list

DEFAULT_TASKS = [
    ("T01","拆除工程",3,[],2,3000),
    ("T02","水电改造",7,["T01"],3,8000),
    ("T03","墙体砌筑",5,["T02"],2,5000),
    ("T04","防水工程",3,["T03"],2,3000),
    ("T05","泥瓦铺贴",10,["T04"],3,12000),
    ("T06","木工吊顶",7,["T05"],2,8000),
    ("T07","油漆工程",7,["T06"],3,6000),
    ("T08","安装工程",5,["T07"],2,5000),
    ("T09","地板铺设",3,["T07"],2,4000),
    ("T10","竣工验收",2,["T08","T09"],1,2000),
]

def generate_schedule(scene, start_date=None) -> Schedule:
    tasks = []
    for tid, name, dur, deps, workers, cost in DEFAULT_TASKS:
        tasks.append(Task(tid, name, dur, deps, workers, cost))
    
    # Forward pass
    for t in tasks:
        if not t.dependencies:
            t.early_start = 0
        else:
            t.early_start = max(
                (next(tt for tt in tasks if tt.id==d).early_finish for d in t.dependencies), default=0
            )
        t.early_finish = t.early_start + t.duration_days
    
    max_finish = max(t.early_finish for t in tasks)
    
    # Backward pass - find critical path
    for t in reversed(tasks):
        if t.id == tasks[-1].id:
            late_finish = max_finish
        else:
            successors = [tt for tt in tasks if t.id in tt.dependencies]
            late_finish = min((tt.early_start for tt in successors), default=max_finish)
        if late_finish - t.duration_days == t.early_start:
            t.is_critical = True
    
    critical = [t for t in tasks if t.is_critical]
    total_cost = sum(t.cost_estimate for t in tasks)
    
    milestones = [
        f"Day 0: 开工大吉",
        f"Day {tasks[2].early_finish}: 水电验收",
        f"Day {tasks[4].early_finish}: 泥瓦验收",
        f"Day {tasks[7].early_finish}: 油漆验收",
        f"Day {max_finish}: 竣工验收",
    ]
    
    return Schedule(tasks, max_finish, critical, total_cost, milestones)

def print_schedule(sch):
    lines=["="*60,f"SCHEDULE: {sch.total_days} days | Critical Path: {len(sch.critical_path)} tasks","="*60]
    for t in sch.tasks:
        cp = " [CRITICAL]" if t.is_critical else ""
        lines.append(f"  {t.id} {t.name}: {t.duration_days}d (Day{t.early_start}-{t.early_finish}) | {t.workers}人 | {t.cost_estimate:,}{cp}")
    lines.append(f"\nMILESTONES:")
    for m in sch.milestones: lines.append(f"  {m}")
    lines.append(f"\nTotal Cost: {sch.total_cost:,}")
    lines.append("="*60)
    t="\n".join(lines); print(t); return t