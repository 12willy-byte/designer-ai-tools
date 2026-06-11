"""全房 3D 模型生成器 v2
RoomPlan JSON → 全房 3D 模型 + 网页查看器
修复: 门窗实体 + 房间内部结构 + 自带浏览器查看
"""
import json, os, sys, math, base64
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# 材质颜色 (RGBA)
C_WALL    = [210, 200, 190, 255]   # 暖灰
C_WALL2   = [195, 185, 175, 255]   # 墙另一面
C_FLOOR   = [180, 160, 130, 255]   # 木地板
C_CEIL    = [240, 240, 235, 255]   # 白色天花
C_DOOR    = [160, 130, 100, 255]   # 木色门
C_DOOR2   = [170, 140, 110, 255]   # 门框
C_WINDOW  = [200, 220, 240, 255]   # 玻璃
C_WINFRAME= [80, 80, 80, 255]     # 窗框
C_BEAM    = [170, 170, 170, 255]   # 梁
C_COLUMN  = [170, 170, 170, 255]   # 柱


def tform_point(m, x, y, z):
    return np.array([m[0]*x+m[4]*y+m[8]*z+m[12],
                     m[1]*x+m[5]*y+m[9]*z+m[13],
                     m[2]*x+m[6]*y+m[10]*z+m[14]])


def create_box(center, w, h, d, color):
    """创建带颜色的盒子"""
    box = trimesh.primitives.Box(extents=[w, h, d])
    box.apply_translation(center)
    box.visual.vertex_colors = color
    return box


def wall_segments(length_mm, height_mm, thickness, transform, openings, color):
    """带门窗洞口的墙体：分段生成"""
    # openings: [(pos_mm, width_mm, type), ...]
    segs = []
    prev = 0
    for pos, w, typ in sorted(openings, key=lambda x: x[0]):
        if pos > prev:
            segs.append((prev, pos))
        prev = pos + w
    if prev < length_mm:
        segs.append((prev, length_mm))

    meshes = []
    for s, e in segs:
        if e - s < 10: continue
        c = s + (e - s) / 2
        box = trimesh.primitives.Box(extents=[e-s, height_mm, thickness])
        # 把盒子变换到墙面位置
        t = np.eye(4)
        t[:3, 0] = transform[:3, 0]  # x轴=墙方向
        t[:3, 1] = transform[:3, 1]  # y轴=向上
        t[:3, 2] = transform[:3, 2]  # z轴=法线
        # 位置：沿墙方向偏移c
        origin = transform[:3, 3]
        x_dir = transform[:3, 0]
        z_dir = transform[:3, 2]
        t[:3, 3] = origin + x_dir * (c - length_mm/2) + z_dir * (thickness/2)
        t[:3, 3] = t[:3, 3] + x_dir * 0  # 对齐
        box.apply_transform(t)
        box.visual.vertex_colors = color
        meshes.append(box)
    return meshes


def build_3d_model(roomplan_path, output_glb, conditions_path=None):
    with open(roomplan_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    surfaces = data.get("surfaces", [])
    rooms_list = data.get("rooms", [])

    # 配色
    wall_color = C_WALL
    if conditions_path and os.path.exists(conditions_path):
        with open(conditions_path, "r", encoding="utf-8") as f:
            cond = json.load(f)
        tone = cond.get("style", {}).get("color_tone", "中性色")
        if "暖" in str(tone):
            wall_color = [220, 205, 185, 255]

    all_meshes = []
    wall_map = {s["identifier"]: s for s in surfaces if s["category"] == "wall"}

    # ── 1. 墙体（带门窗洞口） ──
    for w in surfaces:
        if w["category"] != "wall": continue
        wid = w["identifier"]
        m = w["transform"]
        length = w["dimensions"]["x"]
        height = w["dimensions"]["y"]
        thickness = 120

        # 构建变换矩阵
        x_axis = np.array([m[0], m[1], m[2]])
        y_axis = np.array([m[4], m[5], m[6]])
        z_axis = np.array([m[8], m[9], m[10]])
        origin = np.array([m[12], m[13], m[14]])

        tf = np.eye(4)
        tf[:3, 0] = x_axis / np.linalg.norm(x_axis)
        tf[:3, 1] = y_axis / np.linalg.norm(y_axis)
        tf[:3, 2] = z_axis / np.linalg.norm(z_axis)
        tf[:3, 3] = origin + x_axis * (length/2) + z_axis * (thickness/2)

        # 收集这个墙上的门窗
        openings = []
        for s in surfaces:
            if s["category"] in ("door", "window") and s.get("parentIdentifier") == wid:
                om = s["transform"]
                o_pos = tform_point(om, 0, 0, 0)
                o_local_x = np.dot(o_pos - origin, x_axis / np.linalg.norm(x_axis))
                openings.append((o_local_x, s["dimensions"]["x"], s["category"]))

        # 生成带洞的墙
        seg_meshes = wall_segments(length, height, thickness, tf, openings, wall_color)
        all_meshes.extend(seg_meshes)

    # ── 2. 门实体 ──
    for s in surfaces:
        if s["category"] != "door": continue
        pid = s.get("parentIdentifier")
        if pid not in wall_map: continue
        pw = wall_map[pid]
        pm = pw["transform"]
        sm = s["transform"]
        origin = np.array([pm[12], pm[13], pm[14]])
        x_axis = np.array([pm[0], pm[1], pm[2]]) / np.linalg.norm([pm[0], pm[1], pm[2]])
        z_axis = np.array([pm[8], pm[9], pm[10]]) / np.linalg.norm([pm[8], pm[9], pm[10]])
        y_axis = np.array([pm[4], pm[5], pm[6]]) / np.linalg.norm([pm[4], pm[5], pm[6]])

        d_width = s["dimensions"]["x"]
        d_height = s["dimensions"]["y"]
        d_pos = tform_point(sm, 0, 0, 0)
        d_local = np.dot(d_pos - origin, x_axis)

        # 门扇
        door_center = origin + x_axis * d_local + x_axis * (d_width/2) + y_axis * (d_height/2) + z_axis * 60
        door = create_box(door_center, d_width, d_height, 40, C_DOOR)
        all_meshes.append(door)

        # 门框
        frame_color = C_DOOR2
        # 左边框
        lc = origin + x_axis * d_local + y_axis * (d_height/2) + z_axis * 60
        all_meshes.append(create_box(lc, 30, d_height, 80, frame_color))
        # 右边框
        rc = origin + x_axis * (d_local + d_width) + y_axis * (d_height/2) + z_axis * 60
        all_meshes.append(create_box(rc, 30, d_height, 80, frame_color))
        # 上边框
        tc = origin + x_axis * (d_local + d_width/2) + y_axis * d_height + z_axis * 60
        all_meshes.append(create_box(tc, d_width-30, 30, 80, frame_color))

    # ── 3. 窗实体 ──
    for s in surfaces:
        if s["category"] != "window": continue
        pid = s.get("parentIdentifier")
        if pid not in wall_map: continue
        pw = wall_map[pid]
        pm = pw["transform"]
        sm = s["transform"]
        origin = np.array([pm[12], pm[13], pm[14]])
        x_axis = np.array([pm[0], pm[1], pm[2]]) / np.linalg.norm([pm[0], pm[1], pm[2]])
        y_axis = np.array([pm[4], pm[5], pm[6]]) / np.linalg.norm([pm[4], pm[5], pm[6]])
        z_axis = np.array([pm[8], pm[9], pm[10]]) / np.linalg.norm([pm[8], pm[9], pm[10]])

        w_width = s["dimensions"]["x"]
        w_height = s["dimensions"]["y"]
        w_pos = tform_point(sm, 0, 0, 0)
        # 窗的起点在 sm 变换的原点
        w_local = np.dot(w_pos - origin, x_axis)

        # 玻璃
        glass_center = origin + x_axis * (w_local + w_width/2) + y_axis * (w_height/2 + 1300) + z_axis * 60
        glass = trimesh.primitives.Box(extents=[w_width-40, w_height-40, 10])
        glass_center[1] = w_pos[1] + w_height/2  # Y高度
        gc = origin + x_axis * (w_local + w_width/2) + y_axis * w_pos[1] + y_axis * (w_height/2) + z_axis * 60
        glass.apply_translation(gc)
        glass.visual.vertex_colors = C_WINDOW
        all_meshes.append(glass)

        # 窗框
        fc = origin + x_axis * (w_local + w_width/2) + y_axis * w_pos[1] + y_axis * (w_height/2) + z_axis * 60
        # 简化为一个框
        frame = trimesh.primitives.Box(extents=[w_width, w_height, 30])
        frame.apply_translation(fc)
        frame.visual.vertex_colors = C_WINFRAME
        all_meshes.append(frame)

    # ── 4. 房间地面 ──
    for rm in rooms_list:
        dims = rm.get("dimensions", {})
        rw = dims.get("x", 0)
        rh = dims.get("y", 0)
        if rw <= 0 or rh <= 0: continue

        # 找房间的 floor surface
        for sid in rm.get("surfaces", []):
            s = next((x for x in surfaces if x["identifier"] == sid and x["category"] == "floor"), None)
            if s:
                m = s["transform"]
                origin_f = np.array([m[12], m[13], m[14]])
                x_dir = np.array([m[0], m[1], m[2]]) / max(np.linalg.norm([m[0], m[1], m[2]]), 0.001)
                z_dir = np.array([m[8], m[9], m[10]]) / max(np.linalg.norm([m[8], m[9], m[10]]), 0.001)
                fw = s["dimensions"]["x"]
                fd = s["dimensions"]["y"]
                fc = origin_f + x_dir * (fw/2) + z_dir * (fd/2)
                floor = create_box(fc, fw, 40, fd, C_FLOOR)
                all_meshes.append(floor)
                break

    # ── 5. 梁/柱 ──
    for s in surfaces:
        if s["category"] == "beam":
            m = s["transform"]
            pos = tform_point(m, 0, 0, 0)
            w = s["dimensions"]["x"]
            h = s["dimensions"].get("y", w)
            d = s["dimensions"].get("z", w) if "z" in s["dimensions"] else w
            beam = create_box([pos[0], pos[1] + h/2, pos[2]], w, h, d, C_BEAM)
            all_meshes.append(beam)

        elif s["category"] == "column":
            m = s["transform"]
            pos = tform_point(m, 0, 0, 0)
            size = s["dimensions"]["x"]
            col = create_box([pos[0], 1400, pos[2]], size, 2800, size, C_COLUMN)
            all_meshes.append(col)

    # ── 合并 ──
    if not all_meshes:
        print("No meshes generated!")
        return None

    combined = trimesh.util.concatenate(all_meshes)
    combined.export(output_glb, file_type="glb")

    # ── 同时生成 HTML 查看器 ──
    html_path = output_glb.replace(".glb", ".html")
    with open(output_glb, "rb") as f:
        glb_b64 = base64.b64encode(f.read()).decode()

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>全房3D模型</title>
<style>body{{margin:0;overflow:hidden;font-family:'Microsoft YaHei',sans-serif}}
#info{{position:absolute;bottom:20px;left:50%;transform:translateX(-50%);
background:rgba(0,0,0,0.7);color:#fff;padding:10px 24px;border-radius:20px;
font-size:14px;pointer-events:none;z-index:10}}</style></head><body>
<div id="info"> 鼠标拖拽旋转 · 滚轮缩放 </div>
<script type="importmap">
{{"imports":{{"three":"https://unpkg.com/three@0.160.0/build/three.module.js",
"three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}}}</script>
<script type="module">
import*as THREE from 'three';
import{{OrbitControls}}from 'three/addons/controls/OrbitControls.js';
import{{GLTFLoader}}from 'three/addons/loaders/GLTFLoader.js';

const scene=new THREE.Scene();
scene.background=new THREE.Color(0xf0f0f0);

const camera=new THREE.PerspectiveCamera(45,window.innerWidth/window.innerHeight,1,100000);
camera.position.set(5000,4000,5000);

const renderer=new THREE.WebGLRenderer({{antialias:true}});
renderer.setSize(window.innerWidth,window.innerHeight);
renderer.shadowMap.enabled=true;
document.body.appendChild(renderer.domElement);

const controls=new OrbitControls(camera,renderer.domElement);
controls.target.set(5000,1400,4000);
controls.update();

// 灯光
const dirLight=new THREE.DirectionalLight(0xffffff,1);
dirLight.position.set(5000,5000,5000);
scene.add(dirLight);
const ambient=new THREE.AmbientLight(0x808080,0.5);
scene.add(ambient);

// 网格地面
const gridHelper=new THREE.GridHelper(20000,20,0x888888,0xcccccc);
gridHelper.position.set(5000,0,4000);
scene.add(gridHelper);

// 加载 GLB
const loader=new GLTFLoader();
const glbData=atob('{glb_b64}');
const blob=new Blob([new Uint8Array([...glbData].map(c=>c.charCodeAt(0)))],{{type:'model/gltf-binary'}});
const url=URL.createObjectURL(blob);
loader.load(url,(gltf)=>{{scene.add(gltf.scene);URL.revokeObjectURL(url);
const box=new THREE.Box3().setFromObject(gltf.scene);
const center=box.getCenter(new THREE.Vector3());
controls.target.copy(center);
camera.position.set(center.x+5000,center.y+3000,center.z+5000);
controls.update();
}},undefined,(e)=>console.error(e));

window.addEventListener('resize',()=>{{camera.aspect=window.innerWidth/window.innerHeight;camera.updateProjectionMatrix();renderer.setSize(window.innerWidth,window.innerHeight);}});

function animate(){{requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);}}
animate();
</script></body></html>"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("GLB:", output_glb)
    print("HTML:", html_path)
    print("Faces:", len(combined.faces))
    print("Vertices:", len(combined.vertices))
    return combined


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "templates/sample_roomplan.json"
    cond = sys.argv[2] if len(sys.argv) > 2 else "templates/设计条件.json"
    out = sys.argv[3] if len(sys.argv) > 3 else "templates/real_output/全房模型.glb"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = build_3d_model(inp, out, cond if os.path.exists(cond) else None)
    if r:
        sz = os.path.getsize(out)
        print("GLB size: %d bytes" % sz)
