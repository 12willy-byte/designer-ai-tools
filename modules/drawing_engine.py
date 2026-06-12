"""从3D模型生成平面图 (重写)
原理: 将场景的墙线正交投影到 XZ 平面 → DXF
"""
import os, sys, math
import numpy as np
import ezdxf
from ezdxf.enums import TextEntityAlignment

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from scene3d_engine import Scene3D


def generate_floor_plan(scene, dxf_path):
    """从 3D 场景生成精确的平面图 DXF"""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # 图层
    layers = {
        "墙线": {"color": 7, "lw": 50},
        "门窗": {"color": 5, "lw": 35},
        "填充": {"color": 8, "lw": 9},
        "尺寸标注": {"color": 2, "lw": 9},
        "房间名": {"color": 6, "lw": 9},
    }
    for name, props in layers.items():
        doc.layers.add(name, dxfattribs={"color": props["color"], "lineweight": props["lw"]})

    # 收集所有墙在 XZ 平面上的投影线
    wall_lines = []
    door_lines = []
    window_lines = []

    for mesh, _, typ in scene.meshes:
        verts = mesh.vertices
        edges = mesh.edges_unique

        for edge_idx in edges:
            if len(edge_idx) < 2: continue
            v1, v2 = verts[edge_idx[0]], verts[edge_idx[1]]
            # 只取顶部(Y值较大)的边作为平面图墙线
            y_threshold = 100  # mm
            if v1[1] > 2700 or v2[1] > 2700:  # 接近顶部的边
                x1, z1 = v1[0], v1[2]
                x2, z2 = v2[0], v2[2]
                length = math.hypot(x2-x1, z2-z1)
                if length > 50:  # 忽略太短的线
                    target = wall_lines if typ == "wall" else (door_lines if typ == "door" else window_lines)
                    target.append(((x1, z1), (x2, z2)))

    # 写墙线
    for (x1, z1), (x2, z2) in wall_lines:
        msp.add_line((x1, z1), (x2, z2), dxfattribs={"layer": "墙线"})

    # 写门窗
    for (x1, z1), (x2, z2) in door_lines:
        msp.add_line((x1, z1), (x2, z2), dxfattribs={"layer": "门窗"})
    for (x1, z1), (x2, z2) in window_lines:
        msp.add_line((x1, z1), (x2, z2), dxfattribs={"layer": "门窗"})

    # 尺寸标注
    # 找出所有 X 方向和 Z 方向的墙线范围
    all_x = [p[0] for line in wall_lines for p in line]
    all_z = [p[1] for line in wall_lines for p in line]
    if all_x and all_z:
        min_x, max_x = min(all_x), max(all_x)
        min_z, max_z = min(all_z), max(all_z)
        total_w = max_x - min_x
        total_d = max_z - min_z

        if total_w > 0 and total_d > 0:
            # 总尺寸标注
            off = 500
            # X方向
            msp.add_line((min_x, min_z-off), (max_x, min_z-off), dxfattribs={"layer": "尺寸标注"})
            msp.add_line((min_x, min_z-off+100), (min_x, min_z-off-100), dxfattribs={"layer": "尺寸标注"})
            msp.add_line((max_x, min_z-off+100), (max_x, min_z-off-100), dxfattribs={"layer": "尺寸标注"})
            msp.add_text("%.0f" % total_w, height=250,
                        dxfattribs={"layer": "尺寸标注"}).set_placement(
                            ((min_x+max_x)/2, min_z-off-100), align=TextEntityAlignment.CENTER)

            # Z方向
            msp.add_line((min_x-off, min_z), (min_x-off, max_z), dxfattribs={"layer": "尺寸标注"})
            msp.add_line((min_x-off+100, min_z), (min_x-off-100, min_z), dxfattribs={"layer": "尺寸标注"})
            msp.add_line((min_x-off+100, max_z), (min_x-off-100, max_z), dxfattribs={"layer": "尺寸标注"})
            msp.add_text("%.0f" % total_d, height=250,
                        dxfattribs={"layer": "尺寸标注"}).set_placement(
                            (min_x-off-100, (min_z+max_z)/2), align=TextEntityAlignment.CENTER)

    # 房间名
    for rm in scene.rooms_data:
        name = rm.get("displayName", "")
        dims = rm.get("dimensions", {})
        w = dims.get("x", 0)
        h = dims.get("y", 0)
        # 放在房间中心
        # 从 floor 或 walls 取中心点
        cx, cz = 0, 0
        count = 0
        for mesh, rn, typ in scene.meshes:
            if rn == name and typ == "floor":
                center = mesh.centroid
                cx, cz = center[0], center[2]
                count += 1
                break

        if count == 0:
            # 近似位置
            cx, cz = w/2, h/2

        msp.add_text("%s\n%d×%d\n%.1f m2" % (name, w, h, w*h/1e6), height=250,
                    dxfattribs={"layer": "房间名"}).set_placement(
                        (cx, cz), align=TextEntityAlignment.CENTER)

    doc.saveas(dxf_path)
    print("平面图:", dxf_path, os.path.getsize(dxf_path), "bytes")
    return dxf_path


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "../templates/sample_roomplan.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "../templates/concept_output/平面图_v3.dxf"
    cond = sys.argv[3] if len(sys.argv) > 3 else None

    scene = Scene3D(inp, cond)
    generate_floor_plan(scene, out)
