"""全房 3D 模型生成器
RoomPlan JSON → 全房 3D 模型 (GLB格式)
支持: 墙/门/窗/梁/柱 → 所有结构
"""
import json, os, sys, math
import numpy as np
import trimesh
import pygltflib

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def tform_point(m, x, y, z):
    """4x4 矩阵变换点"""
    return np.array([
        m[0]*x + m[4]*y + m[8]*z + m[12],
        m[1]*x + m[5]*y + m[9]*z + m[13],
        m[2]*x + m[6]*y + m[10]*z + m[14]
    ])


def make_box(center, size, color=None):
    """创建一个盒子 mesh"""
    box = trimesh.primitives.Box(extents=size, transform=np.eye(4))
    box.apply_translation(center)
    if color:
        box.visual.vertex_colors = color
    return box


def build_3d_model(roomplan_json_path, output_glb_path, conditions_json_path=None):
    """从 RoomPlan JSON 构建全房 3D 模型"""
    with open(roomplan_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 加载设计条件（获取配色）
    wall_color = [200, 190, 180, 255]    # 暖灰
    floor_color = [190, 170, 140, 255]   # 木色
    ceiling_color = [240, 240, 240, 255] # 白色
    door_color = [180, 160, 140, 255]    # 木色门
    window_color = [200, 220, 240, 255]  # 玻璃色
    beam_color = [180, 180, 180, 255]    # 灰色
    column_color = [180, 180, 180, 255]  # 灰色

    if conditions_json_path and os.path.exists(conditions_json_path):
        with open(conditions_json_path, "r", encoding="utf-8") as f:
            cond = json.load(f)
        # 如果有色彩方案，可以提取颜色
        # 简单从风格判断
        style = cond.get("style", {})
        tone = style.get("color_tone", "中性色")
        if "暖" in tone:
            wall_color = [220, 205, 190, 255]
        elif "冷" in tone:
            wall_color = [195, 205, 215, 255]
        elif "黑白" in tone:
            wall_color = [230, 230, 230, 255]

    surfaces = data.get("surfaces", [])
    rooms = data.get("rooms", [])

    # 构建索引
    wall_map = {}
    for s in surfaces:
        if s["category"] == "wall":
            wall_map[s["identifier"]] = s

    all_meshes = []

    # ── 1. 墙体 ──
    for w in surfaces:
        if w["category"] != "wall":
            continue
        wid = w["identifier"]
        m = w["transform"]
        length = w["dimensions"]["x"]
        height = w["dimensions"]["y"]
        thickness = 120  # mm

        # 墙的中心点
        center = tform_point(m, length/2, height/2, 0)

        # 墙的朝向（局部 Z 轴方向就是墙的法线方向）
        z_axis = np.array([m[8], m[9], m[10]])
        z_axis = z_axis / np.linalg.norm(z_axis)
        y_axis = np.array([m[4], m[5], m[6]])
        y_axis = y_axis / np.linalg.norm(y_axis)
        x_axis = np.array([m[0], m[1], m[2]])
        x_axis = x_axis / np.linalg.norm(x_axis)

        # 构建墙的变换矩阵
        wall_transform = np.eye(4)
        wall_transform[:3, 0] = x_axis
        wall_transform[:3, 1] = y_axis
        wall_transform[:3, 2] = z_axis
        wall_transform[:3, 3] = center
        wall_transform[:3, 3] -= x_axis * length / 2  # 原点在中心
        wall_transform[:3, 3] -= z_axis * thickness / 2  # Z轴中心偏移

        # 找到这个墙上的 openings
        openings = []
        for s in surfaces:
            if s["category"] in ("door", "window") and s.get("parentIdentifier") == wid:
                openings.append(s)

        if not openings:
            # 没洞的墙：整面墙
            box = trimesh.primitives.Box(
                extents=[length, height, thickness],
                transform=wall_transform
            )
            box.visual.vertex_colors = wall_color
            all_meshes.append(box)
        else:
            # 有洞的墙：分段生成
            # 收集洞口位置
            opening_intervals = []
            for o in openings:
                om = o["transform"]
                o_pos = tform_point(om, 0, 0, 0)
                # 计算沿墙的位置
                o_local_x = np.dot(o_pos - tform_point(m, 0, 0, 0), x_axis)
                o_width = o["dimensions"]["x"]
                opening_intervals.append((o_local_x, o_local_x + o_width, o["category"]))

            # 按位置排序
            opening_intervals.sort(key=lambda x: x[0])

            # 分段：左段、中段(洞口之间)、右段
            segments = []
            prev_end = 0
            for o_start, o_end, o_type in opening_intervals:
                if o_start > prev_end:
                    segments.append((prev_end, o_start))  # 实心段
                prev_end = o_end
            if prev_end < length:
                segments.append((prev_end, length))  # 末端实心段

            # 生成每段
            for seg_start, seg_end in segments:
                if seg_end - seg_start < 10:
                    continue  # 忽略太小的段
                seg_center_x = (seg_start + seg_end) / 2
                seg_length = seg_end - seg_start

                seg_transform = wall_transform.copy()
                seg_transform[:3, 3] += x_axis * (seg_center_x - length/2)

                box = trimesh.primitives.Box(
                    extents=[seg_length, height, thickness],
                    transform=seg_transform
                )
                box.visual.vertex_colors = wall_color
                all_meshes.append(box)

    # ── 2. 地面 ──
    for rm in rooms:
        dims = rm.get("dimensions", {})
        w = dims.get("x", 0)
        h_num = dims.get("y", 0)
        if w <= 0 or h_num <= 0:
            continue

        # 找这个房间的地面（第一个 floor surface）
        room_surfaces = rm.get("surfaces", [])
        floor_info = None
        for sid in room_surfaces:
            s = next((x for x in surfaces if x["identifier"] == sid and x["category"] == "floor"), None)
            if s:
                floor_info = s
                break

        if floor_info:
            m_fl = floor_info["transform"]
            origin = tform_point(m_fl, 0, 0, 0)
            x_dir = np.array([m_fl[0], m_fl[1], m_fl[2]])
            z_dir = np.array([m_fl[8], m_fl[9], m_fl[10]])

            x_dir = x_dir / np.linalg.norm(x_dir)
            z_dir = z_dir / np.linalg.norm(z_dir)

            # 地面是矩形，在 XZ 平面
            floor_w = floor_info["dimensions"]["x"]
            floor_d = floor_info["dimensions"]["y"]

            floor_transform = np.eye(4)
            floor_transform[:3, 0] = x_dir
            floor_transform[:3, 1] = np.array([0, 1, 0])  # Y up
            floor_transform[:3, 2] = z_dir
            floor_transform[:3, 3] = origin
            floor_transform[:3, 3] += x_dir * floor_w / 2
            floor_transform[:3, 3] += z_dir * floor_d / 2

            floor = trimesh.primitives.Box(
                extents=[floor_w, 50, floor_d],  # 50mm 厚
                transform=floor_transform
            )
            floor.visual.vertex_colors = floor_color
            all_meshes.append(floor)

    # ── 3. 梁 ──
    for s in surfaces:
        if s["category"] != "beam":
            continue
        m = s["transform"]
        pos = tform_point(m, 0, 0, 0)
        w = s["dimensions"]["x"]
        h = s["dimensions"].get("y", w)
        d = s["dimensions"].get("z", w) if "z" in s["dimensions"] else w

        beam = trimesh.primitives.Box(extents=[w, h, d])
        beam.apply_translation(pos)
        beam.visual.vertex_colors = beam_color
        all_meshes.append(beam)

    # ── 4. 柱 ──
    for s in surfaces:
        if s["category"] != "column":
            continue
        m = s["transform"]
        pos = tform_point(m, 0, 0, 0)
        size = s["dimensions"]["x"]
        col = trimesh.primitives.Box(extents=[size, 2800, size])
        col.apply_translation([pos[0], 1400, pos[2]])
        col.visual.vertex_colors = column_color
        all_meshes.append(col)

    # ── 合并所有 mesh ──
    if not all_meshes:
        print("No meshes generated!")
        return

    combined = trimesh.util.concatenate(all_meshes)

    # ── 导出 GLB ──
    combined.export(output_glb_path, file_type="glb")
    print("Output:", output_glb_path)
    print("Vertices:", len(combined.vertices))
    print("Faces:", len(combined.faces))
    print("Bounds:", combined.bounds)
    return combined


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else "templates/sample_roomplan.json"
    cond = sys.argv[2] if len(sys.argv) > 2 else "templates/设计条件.json"
    out = sys.argv[3] if len(sys.argv) > 3 else "templates/concept_output/全房模型.glb"
    os.makedirs(os.path.dirname(out), exist_ok=True)

    if not os.path.exists(inp):
        print("File not found:", inp)
        sys.exit(1)

    result = build_3d_model(inp, out, cond if os.path.exists(cond) else None)
    if result:
        sz = os.path.getsize(out)
        print("File size:", sz, "bytes")


if __name__ == "__main__":
    main()
