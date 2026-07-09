"""
Blender 渲染脚本 - 从 Scene3D JSON 构建场景并渲染效果图
用法: blender --background --python render_blender.py -- scene.json output.png

在 Blender 外部运行: python render_blender.py scene.json output.png
(会自动查找并调用 Blender)
"""
import os, sys, json, subprocess, argparse, math


def render_in_blender(scene_json_path: str, output_path: str,
                      resolution: int = 1920, samples: int = 128):
    """调用 Blender 进行渲染 (使用 subprocess)"""

    script_dir = os.path.dirname(os.path.abspath(__file__))
    blender_script = os.path.join(script_dir, "_blender_render.py")

    # 写入 Blender 内部脚本
    _write_blender_script(blender_script, scene_json_path, output_path, resolution, samples)

    # 查找 Blender
    blender_exe = _find_blender()
    if not blender_exe:
        print("Blender not found. Install Blender or set BLENDER_EXE env var.")
        print("Manual: blender --background --python", blender_script, "--", scene_json_path, output_path)
        return None

    print(f"Blender: {blender_exe}")
    print(f"Rendering {scene_json_path} -> {output_path}")

    cmd = [blender_exe, "--background", "--python", blender_script]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print("Blender stderr:", result.stderr[-500:])
        return None

    # 检查输出
    if os.path.exists(output_path):
        size_kb = os.path.getsize(output_path) / 1024
        print(f"Rendered: {output_path} ({size_kb:.0f} KB)")
        return output_path
    else:
        print("Render failed - no output file")
        print(result.stdout[-500:])
        return None


def _find_blender():
    """查找 Blender 可执行文件"""
    # 环境变量
    env = os.environ.get("BLENDER_EXE", "")
    if env and os.path.exists(env):
        return env

    # Windows 默认路径
    candidates = [
        r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
        r"C:\Program Files\Blender Foundation\Blender 3.3\blender.exe",
        # Mac
        "/Applications/Blender.app/Contents/MacOS/Blender",
        # Linux
        "/usr/bin/blender",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # PATH 查找
    try:
        result = subprocess.run(["blender", "--version"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return "blender"
    except Exception:
        pass

    return None


def _write_blender_script(script_path, scene_json, output, resolution, samples):
    """生成 Blender 内部 Python 脚本"""
    import textwrap
    code = textwrap.dedent(f'''
    import bpy, json, math, os, sys

    # 清空场景
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # 加载 Scene3D 数据
    with open(r"{scene_json}", "r", encoding="utf-8") as f:
        data = json.load(f)

    # 单位: 米 (从 mm 转换)
    def mm2m(v): return v / 1000

    # 材质
    mats = {{}}
    mat_defs = {{
        "wall":     ((0.50,0.56,0.63,1), 0.7, 0.05),
        "floor":    ((0.84,0.81,0.75,1), 0.8, 0.0),
        "door":     ((0.91,0.57,0.23,1), 0.5, 0.1),
        "window":   ((0.29,0.56,0.85,0.5), 0.2, 0.3),
        "furniture":((0.79,0.66,0.43,1), 0.6, 0.05),
        "beam":     ((1.0,0.84,0.0,0.4), 0.4, 0.2),
        "column":   ((0.55,0.27,0.07,1), 0.3, 0.3),
    }}
    for name, (color, rough, metal) in mat_defs.items():
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = rough
            bsdf.inputs["Metallic"].default_value = metal
            if color[3] < 1:
                mat.blend_method = 'BLEND'
        mats[name] = mat

    def add_box(name, w, h, d, mat_name, location, rotation_z=0):
        bpy.ops.mesh.primitive_cube_add(size=1)
        obj = bpy.context.active_object
        obj.name = name
        obj.scale = (w, h, d)
        obj.location = location
        obj.rotation_euler = (0, 0, rotation_z)
        obj.data.materials.append(mats.get(mat_name))
        return obj

    # 地面
    for room in data.get("rooms", []):
        pts = room.get("floor_points", [])
        if len(pts) < 3: continue
        verts = [(mm2m(p["x"]), mm2m(p["y"]), mm2m(p["z"])) for p in pts]
        edges = [(i, (i+1)%len(verts)) for i in range(len(verts))]
        faces = [list(range(len(verts)))]

        mesh = bpy.data.meshes.new("floor_mesh")
        obj = bpy.data.objects.new(f"floor_{room['id'][:8]}", mesh)
        bpy.context.collection.objects.link(obj)
        mesh.from_pydata(verts, edges, faces)
        mesh.update()
        obj.data.materials.append(mats["floor"])

    # 墙体
    for wall in data.get("walls", []):
        sx, sz = mm2m(wall["start"]["x"]), mm2m(wall["start"]["z"])
        ex, ez = mm2m(wall["end"]["x"]), mm2m(wall["end"]["z"])
        wall_h = mm2m(wall.get("height_mm", 2800))
        thick = mm2m(wall.get("thickness_mm", 120))
        dx, dz = ex-sx, ez-sz
        wall_len = math.sqrt(dx*dx + dz*dz) or 0.01
        angle = math.atan2(dz, dx)
        cx, cz = (sx+ex)/2, (sz+ez)/2

        # 墙段 (扣除开口)
        segs = [[0, wall_len]]
        for op in sorted(wall.get("openings", []), key=lambda o: o["offset_mm"]):
            off = mm2m(op["offset_mm"])
            ow = mm2m(op["width_mm"])
            segs = [[s,e] for s,e in segs for ns,ne in [
                (s, min(e, off)), (max(s, off+ow), e)] if ne-ns > 0.001]

        for s, e in segs:
            slen = e - s
            scx = sx + dx * (s + slen/2) / wall_len
            scz = sz + dz * (s + slen/2) / wall_len
            add_box(f"wall_{wall['id'][:8]}", slen, wall_h, thick, "wall",
                   (scx, wall_h/2, scz), angle)

        # 门窗
        for op in wall.get("openings", []):
            off = mm2m(op["offset_mm"])
            ow = mm2m(op["width_mm"])
            oh = mm2m(op["height_mm"])
            is_door = op["type"] == "door"
            mat = "door" if is_door else "window"
            oy = oh/2 if is_door else mm2m(op.get("sill_height_mm", 0)) + oh/2
            ocx = sx + dx * (off + ow/2) / wall_len
            ocz = sz + dz * (off + ow/2) / wall_len
            add_box(f"op_{op['id'][:8]}", ow, oh, thick*1.1, mat,
                   (ocx, oy, ocz), angle)

    # 家具
    for furn in data.get("furniture", []):
        fw, fd, fh = mm2m(furn["width_mm"]), mm2m(furn["depth_mm"]), mm2m(furn["height_mm"])
        px, pz = mm2m(furn["position"]["x"]), mm2m(furn["position"]["z"])
        add_box(furn["name"], fw, fh, fd, "furniture", (px+fw/2, fh/2, pz+fd/2))

    # 梁
    for beam in data.get("beams", []):
        bw, bd, bl = mm2m(beam["width_mm"]), mm2m(beam["depth_mm"]), mm2m(beam["length_mm"])
        px, py, pz = mm2m(beam["position"]["x"]), mm2m(beam["position"]["y"]), mm2m(beam["position"]["z"])
        add_box("beam", bl, bd, bw, "beam", (px+bl/2, py+bd/2, pz+bw/2))

    # 柱
    for col in data.get("columns", []):
        cw, cd, ch = mm2m(col["width_mm"]), mm2m(col["depth_mm"]), mm2m(col.get("height_mm",2800))
        px, py, pz = mm2m(col["position"]["x"]), mm2m(col["position"]["y"]), mm2m(col["position"]["z"])
        add_box("column", cw, ch, cd, "column", (px+cw/2, py+ch/2, pz+cd/2))

    # 相机
    bpy.ops.object.camera_add(location=(8, -6, 8))
    cam = bpy.context.active_object
    cam.rotation_euler = (math.radians(55), 0, math.radians(45))
    bpy.context.scene.camera = cam

    # 光照
    bpy.ops.object.light_add(type='SUN', location=(10, -5, 15))
    sun = bpy.context.active_object
    sun.data.energy = 3
    sun.data.angle = math.radians(5)

    # 天空环境
    world = bpy.context.scene.world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Strength"].default_value = 0.3
        bg.inputs["Color"].default_value = (0.6, 0.7, 0.9, 1)

    # 渲染设置
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.render.resolution_x = {resolution}
    scene.render.resolution_y = int({resolution} * 9 / 16)
    scene.render.filepath = r"{output}"
    scene.render.image_settings.file_format = 'PNG'
    scene.cycles.samples = {samples}
    scene.cycles.use_denoising = True

    # 渲染
    print(f"Rendering {resolution}x{int(resolution*9/16)} at {samples} samples...")
    bpy.ops.render.render(write_still=True)
    print("Render complete!")
    ''')

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Blender 渲染 - Scene3D JSON to PNG")
    parser.add_argument("scene", help="Scene3D JSON 路径")
    parser.add_argument("output", nargs="?", default="render_output.png", help="输出 PNG 路径")
    parser.add_argument("--resolution", type=int, default=1920, help="渲染分辨率宽 (默认1920)")
    parser.add_argument("--samples", type=int, default=128, help="Cycles 采样数 (默认128)")
    args = parser.parse_args()

    render_in_blender(args.scene, args.output, args.resolution, args.samples)
