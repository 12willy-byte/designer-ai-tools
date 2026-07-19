# -*- coding: utf-8 -*-
"""
energy_analysis - Building energy efficiency & insulation analysis
Checks: wall/roof U-values, window thermal performance, HVAC sizing.
Based on GB 50189 (Design standard for energy efficiency).
"""
import json, os, math, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dataclasses import dataclass, field

# Typical U-values (W/m2K) for Chinese construction
U_VALUES = {
    "wall_brick_240": 1.8,    # 240mm brick, no insulation
    "wall_brick_240_insulated": 0.6,  # With 50mm EPS
    "wall_concrete_200": 3.0,
    "wall_concrete_200_insulated": 0.45,
    "roof_flat": 2.0,
    "roof_flat_insulated": 0.4,
    "window_single": 5.7,
    "window_double": 2.8,
    "window_low_e": 1.8,
    "floor_ground": 1.5,
}

GB50189_LIMITS = {
    "cold": {"wall": 0.45, "roof": 0.35, "window": 2.5},
    "hot_summer_cold_winter": {"wall": 0.80, "roof": 0.50, "window": 3.0},
    "hot_summer_warm_winter": {"wall": 1.50, "roof": 0.90, "window": 4.0},
}

@dataclass
class EnergyReport:
    climate_zone: str
    wall_u_value: float
    roof_u_value: float
    window_u_value: float
    wall_pass: bool
    roof_pass: bool
    window_pass: bool
    heating_load_kw: float
    cooling_load_kw: float
    recommendations: list = field(default_factory=list)
    annual_energy_saving_potential: str = ""

def analyze_energy(scene, climate_zone="hot_summer_cold_winter") -> EnergyReport:
    """
    Energy efficiency analysis based on Scene3D geometry.
    Estimates heating/cooling loads and checks GB50189 compliance.
    """
    rooms = [_norm(r) for r in (get_rooms(scene))]
    walls = [_norm(w) for w in (get_walls(scene))]
    windows = [_norm(w) for w in (get_windows(scene))]
    
    total_floor = sum(r.get('length_mm',0) * r.get('width_mm',0) / 1e6 for r in rooms)
    
    # Wall area
    total_wall_area = 0
    total_window_area = 0
    for w in walls:
        s, e = w.get('start', [0,0,0]), w.get('end', [0,0,0])
        L = w.get('length_mm', 0) or math.hypot(e[0]-s[0], e[2]-s[2])
        H = w.get('height', w.get('height_mm', 2800))
        total_wall_area += L * H / 1e6
    
    for win in windows:
        total_window_area += win.get('width_mm',0) * win.get('height_mm',0) / 1e6
    
    # Assume default construction
    wall_u = U_VALUES["wall_brick_240"]
    roof_u = U_VALUES["roof_flat"]
    window_u = U_VALUES["window_double"]
    
    limits = GB50189_LIMITS.get(climate_zone, GB50189_LIMITS["hot_summer_cold_winter"])
    
    wall_pass = wall_u <= limits["wall"]
    roof_pass = roof_u <= limits["roof"]
    window_pass = window_u <= limits["window"]
    
    # Heating load estimate: Q = U * A * deltaT
    delta_t_heating = 20  # Indoor 20C - Outdoor avg
    delta_t_cooling = 10  # Outdoor 35C - Indoor 25C
    
    opaque_area = max(0, total_wall_area - total_window_area)
    heating_load = (wall_u * opaque_area + roof_u * max(total_floor,1) + window_u * total_window_area) * delta_t_heating / 1000
    cooling_load = (wall_u * opaque_area + roof_u * max(total_floor,1) + window_u * total_window_area) * delta_t_cooling / 1000
    
    recs = []
    if not wall_pass:
        recs.append(f"墙体U值 {wall_u} > 限值 {limits['wall']}——建议增加50mm保温层")
        recs.append("  → 加装EPS/XPS外保温可降至 {:.1f}".format(U_VALUES["wall_brick_240_insulated"]))
    if not roof_pass:
        recs.append(f"屋顶U值 {roof_u} > 限值 {limits['roof']}——建议增加100mm保温层")
    if not window_pass:
        recs.append(f"窗户U值 {window_u} > 限值 {limits['window']}——建议使用Low-E中空玻璃")
        recs.append("  → Low-E中空玻璃可降至 {:.1f}".format(U_VALUES["window_low_e"]))
    
    if total_floor > 0 and total_window_area / total_floor < 0.12:
        recs.append("窗墙比偏低——可增加南向窗户以利用被动太阳能")
    
    # Savings estimate
    if wall_u > limits["wall"]:
        saving = int(heating_load * 0.35 * 0.5)  # 35% of heating, 0.5 yuan/kWh
        energy_save = f"增加墙体保温后，年供暖可节省约 {heating_load*0.35*1000:.0f} kWh（约¥{saving}）"
    else:
        energy_save = "围护结构热工性能达标"
    
    return EnergyReport(
        climate_zone=climate_zone,
        wall_u_value=round(wall_u, 2),
        roof_u_value=round(roof_u, 2),
        window_u_value=round(window_u, 2),
        wall_pass=wall_pass,
        roof_pass=roof_pass,
        window_pass=window_pass,
        heating_load_kw=round(heating_load, 2),
        cooling_load_kw=round(cooling_load, 2),
        recommendations=recs,
        annual_energy_saving_potential=energy_save,
    )

from core.scene_utils import normalize as _n, get_rooms, get_walls, get_doors, get_windows
_norm = _n  # alias for modules that use _norm