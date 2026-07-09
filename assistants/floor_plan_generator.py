"""
平面图生成器 - 从 3D 场景正交投影生成专业建筑平面图
输出: DXF (可编辑) + PNG (快速预览)
"""
import os, sys, math, json
import numpy as np
import ezdxf
from ezdxf.enums import TextEntityAlignment
import matplotlib
import matplotlib.font_manager as fm
# Register CJK font for Chinese text
_cjk_fonts = ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simsun.ttc', 'C:/Windows/Fonts/simhei.ttf']
for _fp in _cjk_fonts:
    if __import__('os').path.exists(_fp):
        fm.fontManager.addfont(_fp)
        _prop = fm.FontProperties(fname=_fp)
        matplotlib.rcParams['font.family'] = _prop.get_name()
        break
matplotlib.rcParams['axes.unicode_minus'] = False

from matplotlib import pyplot as plt
from matplotlib.patches import Polygon, Rectangle, Arc, Circle, FancyBboxPatch
import matplotlib.patheffects as pe

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene3d import Scene3D


# ============================================================
# DXF 输出
# ============================================================

def export_dxf(scene: Scene3D, output_path: str) -> str:
    """从 3D 场景生成 DXF 平面图 (符合中国建筑制图习惯)"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 图层定义
    LAYERS = {
        "墙体": {"color": 7, "lw": 50},
        "墙体填充": {"color": 8, "lw": 0},
        "门窗": {"color": 5, "lw": 30},
        "尺寸标注": {"color": 2, "lw": 0},
        "房间标注": {"color": 6, "lw": 0},
        "家具": {"color": 4, "lw": 20},
        "梁": {"color": 253, "lw": 30},
        "柱": {"color": 253, "lw": 30},
        "图框": {"color": 7, "lw": 0},
    }
    for name, props in LAYERS.items():
        doc.layers.add(name, dxfattribs={"color": props["color"], "lineweight": props["lw"]})

    # ── 墙线 (双线) ──
    for wall in scene.walls.values():
        dx, dz = wall.direction
        nx, nz = -dz, dx  # 法向量
        half_t = wall.thickness_mm / 2

        # 墙起点/终点沿法向量偏移
        x1 = wall.start.x; z1 = wall.start.z
        x2 = wall.end.x;   z2 = wall.end.z

        # 四角
        corners = [
            (x1 + nx*half_t, z1 + nz*half_t),
            (x1 - nx*half_t, z1 - nz*half_t),
            (x2 - nx*half_t, z2 - nz*half_t),
            (x2 + nx*half_t, z2 + nz*half_t),
        ]
        # 画实心墙段
        for s, e in wall.opening_segments():
            p1 = (x1 + dx*s + nx*half_t, z1 + dz*s + nz*half_t)
            p2 = (x1 + dx*s - nx*half_t, z1 + dz*s - nz*half_t)
            p3 = (x1 + dx*e - nx*half_t, z1 + dz*e - nz*half_t)
            p4 = (x1 + dx*e + nx*half_t, z1 + dz*e + nz*half_t)
            msp.add_lwpolyline([p1, p2, p3, p4, p1], dxfattribs={"layer": "墙体"})

        # 开口处画门窗
        for op in wall.openings:
            oc = x1 + dx*op.offset_mm + dx*op.width_mm/2, z1 + dz*op.offset_mm + dz*op.width_mm/2
            if op.type.value == "door":
                # 简化: 在开口处画门线
                msp.add_line(
                    (x1+dx*op.offset_mm + nx*half_t, z1+dz*op.offset_mm + nz*half_t),
                    (x1+dx*op.offset_mm - nx*half_t, z1+dz*op.offset_mm - nz*half_t),
                    dxfattribs={"layer": "门窗"})
            elif op.type.value == "window":
                msp.add_line(
                    (x1+dx*op.offset_mm + nx*half_t, z1+dz*op.offset_mm + nz*half_t),
                    (x1+dx*(op.offset_mm+op.width_mm) + nx*half_t, z1+dz*(op.offset_mm+op.width_mm) + nz*half_t),
                    dxfattribs={"layer": "门窗"})

    # ── 梁 ──
    for beam in scene.beams.values():
        p = beam.position
        msp.add_lwpolyline([
            (p.x, p.z), (p.x+beam.length_mm, p.z),
            (p.x+beam.length_mm, p.z+beam.depth_mm), (p.x, p.z+beam.depth_mm), (p.x, p.z)
        ], dxfattribs={"layer": "梁"})

    # ── 柱 ──
    for col in scene.columns.values():
        p = col.position
        msp.add_lwpolyline([
            (p.x, p.z), (p.x+col.width_mm, p.z),
            (p.x+col.width_mm, p.z+col.depth_mm), (p.x, p.z+col.depth_mm), (p.x, p.z)
        ], dxfattribs={"layer": "柱"})

    # ── 家具 ──
    for furn in scene.furniture.values():
        p = furn.position
        pts = [(p.x, p.z), (p.x+furn.width_mm, p.z),
               (p.x+furn.width_mm, p.z+furn.depth_mm), (p.x, p.z+furn.depth_mm)]
        msp.add_lwpolyline(pts + [pts[0]], dxfattribs={"layer": "家具"})
        msp.add_text(furn.name, height=200,
                     dxfattribs={"layer": "家具"}).set_placement(
                         (p.x+furn.width_mm/2, p.z+furn.depth_mm/2),
                         align=TextEntityAlignment.CENTER)

    # ── 房间标注 ──
    for room in scene.rooms.values():
        if len(room.floor_points) < 3: continue
        cx = sum(p.x for p in room.floor_points) / len(room.floor_points)
        cz = sum(p.z for p in room.floor_points) / len(room.floor_points)
        area = room.area_m2
        msp.add_text(f"{room.name}\n{area:.1f}m\²", height=300,
                     dxfattribs={"layer": "房间标注"}).set_placement(
                         (cx, cz), align=TextEntityAlignment.CENTER)

    # ── 尺寸标注 ──
    (mx, mz), (Mx, Mz) = scene.bounds
    off = 1500
    msp.add_line((mx-off, mz-off), (Mx+off, mz-off), dxfattribs={"layer": "尺寸标注"})
    msp.add_line((mx-off, Mz+off), (Mx+off, Mz+off), dxfattribs={"layer": "尺寸标注"})
    msp.add_line((mx-off, mz-off), (mx-off, Mz+off), dxfattribs={"layer": "尺寸标注"})
    msp.add_line((Mx+off, mz-off), (Mx+off, Mz+off), dxfattribs={"layer": "尺寸标注"})

    doc.saveas(output_path)
    return output_path


# ============================================================
# PNG 快速预览 (matplotlib)
# ============================================================

def render_preview(scene: Scene3D, output_path: str = None, show: bool = False):
    """用 matplotlib 渲染建筑平面图预览"""
    fig, ax = plt.subplots(1, 1, figsize=(16, 10), dpi=150)
    ax.set_aspect('equal')
    ax.set_facecolor('#FFFFFF')
    ax.axis('off')

    # 颜色方案
    C_WALL_FILL = '#E8E0D8'  # 墙体填充
    C_WALL_EDGE = '#333333'  # 墙体边线
    C_DOOR = '#8B7355'       # 门
    C_WINDOW = '#87CEEB'     # 窗
    C_BEAM = '#FFD70033'     # 梁(半透明)
    C_COLUMN = '#333333'     # 柱
    C_TEXT = '#1F4E79'       # 文字
    C_ROOM_BG = '#FAFAF5'    # 房间底色

    (mx, mz), (Mx, Mz) = scene.bounds
    margin = 2000
    ax.set_xlim(mx - margin, Mx + margin)
    ax.set_ylim(mz - margin, Mz + margin)

    # 房间底色
    for room in scene.rooms.values():
        if len(room.floor_points) >= 3:
            pts = [(p.x, p.z) for p in room.floor_points]
            poly = Polygon(pts, facecolor=C_ROOM_BG, edgecolor='#DDD', linewidth=0.5, zorder=1)
            ax.add_patch(poly)

    # 墙体
    for wall in scene.walls.values():
        dx, dz = wall.direction
        nx, nz = -dz, dx
        half_t = wall.thickness_mm / 2
        x1, z1 = wall.start.x, wall.start.z

        for s, e in wall.opening_segments():
            p1 = (x1 + dx*s + nx*half_t, z1 + dz*s + nz*half_t)
            p2 = (x1 + dx*s - nx*half_t, z1 + dz*s - nz*half_t)
            p3 = (x1 + dx*e - nx*half_t, z1 + dz*e - nz*half_t)
            p4 = (x1 + dx*e + nx*half_t, z1 + dz*e + nz*half_t)
            poly = Polygon([p1, p2, p3, p4], facecolor=C_WALL_FILL,
                          edgecolor=C_WALL_EDGE, linewidth=1.5, zorder=10)
            ax.add_patch(poly)

    # 门(简化:弧线)
    for op in scene.doors.values():
        for wall in scene.walls.values():
            if op in wall.openings:
                dx, dz = wall.direction
                nx, nz = -dz, dx
                x1, z1 = wall.start.x, wall.start.z
                half_t = wall.thickness_mm / 2
                cx = x1 + dx*op.offset_mm + dx*op.width_mm/2
                cz = z1 + dz*op.offset_mm + dz*op.width_mm/2
                # 画门弧
                arc = Arc((cx, cz), op.width_mm, op.width_mm, angle=0,
                         theta1=0, theta2=90, color=C_DOOR, linewidth=2, zorder=20)
                ax.add_patch(arc)

    # 窗
    for op in scene.windows.values():
        for wall in scene.walls.values():
            if op in wall.openings:
                dx, dz = wall.direction
                nx, nz = -dz, dx
                x1, z1 = wall.start.x, wall.start.z
                half_t = wall.thickness_mm / 2
                cx = x1 + dx*op.offset_mm + dx*op.width_mm/2
                cz = z1 + dz*op.offset_mm + dz*op.width_mm/2
                # 窗线
                ax.plot([x1+dx*op.offset_mm + nx*half_t, x1+dx*(op.offset_mm+op.width_mm) + nx*half_t],
                       [z1+dz*op.offset_mm + nz*half_t, z1+dz*(op.offset_mm+op.width_mm) + nz*half_t],
                       color=C_WINDOW, linewidth=3, zorder=15)

    # 梁
    for beam in scene.beams.values():
        p = beam.position
        rect = Rectangle((p.x, p.z), beam.length_mm, beam.depth_mm,
                        facecolor='#FFD700', alpha=0.3, edgecolor='#CC9900',
                        linewidth=0.5, linestyle='--', zorder=5)
        ax.add_patch(rect)

    # 柱
    for col in scene.columns.values():
        p = col.position
        rect = Rectangle((p.x, p.z), col.width_mm, col.depth_mm,
                        facecolor=C_COLUMN, edgecolor=C_WALL_EDGE, linewidth=1, zorder=25)
        ax.add_patch(rect)

    # 房间标注
    for room in scene.rooms.values():
        if len(room.floor_points) < 3: continue
        cx = sum(p.x for p in room.floor_points) / len(room.floor_points)
        cz = sum(p.z for p in room.floor_points) / len(room.floor_points)
        ax.text(cx, cz, f"{room.name}\n{room.area_m2:.1f}m\u00b2",
               ha='center', va='center', fontsize=9, color=C_TEXT,
               fontweight='bold', zorder=30)

    # 尺寸标注
    off = 1500
    ax.plot([mx-off, Mx+off], [mz-off, mz-off], 'k-', linewidth=0.5, zorder=40)
    ax.plot([mx-off, mx-off], [mz-off+200, mz-off-200], 'k-', linewidth=0.5, zorder=40)
    ax.plot([Mx+off, Mx+off], [mz-off+200, mz-off-200], 'k-', linewidth=0.5, zorder=40)
    ax.text((mx+Mx)/2, mz-off-300, f"{Mx-mx:.0f}mm", ha='center', fontsize=8, zorder=40)

    ax.plot([mx-off, mx-off], [mz-off, Mz+off], 'k-', linewidth=0.5, zorder=40)
    ax.text(mx-off-400, (mz+Mz)/2, f"{Mz-mz:.0f}mm", ha='center', fontsize=8,
           rotation=90, zorder=40)

    # 标题
    ax.set_title(scene.name or "原始结构平面图", fontsize=14, fontweight='bold', pad=20)

    plt.tight_layout()
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        print(f"预览图: {output_path}")
    if show:
        plt.show()
    else:
        plt.close()
    return output_path


def generate_floor_plan(scene: Scene3D, dxf_path: str = None, png_path: str = None):
    """一站式生成 DXF + PNG 平面图"""
    results = {}
    if dxf_path:
        results['dxf'] = export_dxf(scene, dxf_path)
    if png_path:
        results['png'] = render_preview(scene, png_path)
    return results
