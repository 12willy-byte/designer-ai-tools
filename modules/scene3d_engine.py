"""3D 场景引擎 v3 (重构)
核心: 从 RoomPlan 数据构建可计算的 3D 场景
一切图纸/算量/渲染都从场景推导
"""
import json, os, sys, math, base64
import numpy as np
import trimesh

def tform(m, x, y, z):
    return np.array([m[0]*x+m[4]*y+m[8]*z+m[12],
                     m[1]*x+m[5]*y+m[9]*z+m[13],
                     m[2]*x+m[6]*y+m[10]*z+m[14]])


class Scene3D:
    """全房 3D 场景"""
    def __init__(self, roomplan_path, conditions_path=None):
        with open(roomplan_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        self.surfaces = self.data.get("surfaces", [])
        self.rooms_data = self.data.get("rooms", [])
        self.smap = {s["identifier"]: s for s in self.surfaces}
        self.meshes = []  # list of (mesh, room_name, element_type)

        # 构建
        self._build_walls()
        self._build_doors()
        self._build_windows()
        self._build_floors()
        self._build_beams_columns()

    def _build_walls(self):
        wall_thick = 120
        for w in self.surfaces:
            if w["category"] != "wall": continue
            wid, m = w["identifier"], w["transform"]
            length, height = w["dimensions"]["x"], w["dimensions"]["y"]

            o = np.array([m[12], m[13], m[14]])
            xa = np.array([m[0], m[1], m[2]])
            ya = np.array([m[4], m[5], m[6]])
            za = np.array([m[8], m[9], m[10]])

            # 收集开口
            openings = []
            for s in self.surfaces:
                if s.get("parentIdentifier") == wid and s["category"] in ("door","window"):
                    op = tform(s["transform"], 0, 0, 0)
                    ol = np.dot(op - o, xa / max(np.linalg.norm(xa), 1))
                    openings.append((ol, s["dimensions"]["x"], s["dimensions"]["y"], s["category"], op[1]))

            # 分段生成墙段
            segs = []
            prev = 0
            for pos, ww, wh, typ, ybase in sorted(openings, key=lambda x: x[0]):
                if pos > prev + 10:
                    segs.append((prev, pos, 0, height))
                prev = pos + ww
            if prev < length - 10:
                segs.append((prev, length, 0, height))

            for s, e, y0, y1 in segs:
                if e - s < 10: continue
                ctr = e - s
                # 构建8个顶点
                cx = o + xa * (s + (e-s)/2) + ya * (y1/2) + za * (wall_thick/2)
                hw, hh, hd = (e-s)/2, y1/2, wall_thick/2
                verts = np.array([
                    [-hw, -hh, -hd], [ hw, -hh, -hd], [ hw,  hh, -hd], [-hw,  hh, -hd],
                    [-hw, -hh,  hd], [ hw, -hh,  hd], [ hw,  hh,  hd], [-hw,  hh,  hd],
                ])
                # 旋转变换到墙的朝向
                rot = np.eye(3)
                rot[:, 0] = xa / np.linalg.norm(xa)
                rot[:, 1] = ya / np.linalg.norm(ya)
                rot[:, 2] = za / np.linalg.norm(za)
                verts = verts @ rot.T + cx

                faces = np.array([
                    [0,1,2],[0,2,3],[4,5,6],[4,6,7],
                    [0,4,5],[0,5,1],[1,5,6],[1,6,2],
                    [2,6,7],[2,7,3],[3,7,4],[3,4,0],
                ])
                mesh = trimesh.Trimesh(vertices=verts, faces=faces)
                mesh.visual.vertex_colors = [210, 200, 190, 255]
                self.meshes.append((mesh, None, "wall"))

    def _build_doors(self):
        for s in self.surfaces:
            if s["category"] != "door": continue
            pid = s.get("parentIdentifier")
            pw = self.smap.get(pid)
            if not pw: continue

            pm = pw["transform"]
            sm = s["transform"]
            o = np.array([pm[12], pm[13], pm[14]])
            xa = np.array([pm[0], pm[1], pm[2]]) / max(np.linalg.norm([pm[0],pm[1],pm[2]]),1)
            ya = np.array([pm[4], pm[5], pm[6]]) / max(np.linalg.norm([pm[4],pm[5],pm[6]]),1)
            za = np.array([pm[8], pm[9], pm[10]]) / max(np.linalg.norm([pm[8],pm[9],pm[10]]),1)

            dw, dh = s["dimensions"]["x"], s["dimensions"]["y"]
            dp = tform(sm, 0, 0, 0)
            dl = np.dot(dp - o, xa)

            # 门扇
            dc = o + xa*(dl + dw/2) + ya*(dh/2) + za*60
            door = trimesh.primitives.Box(extents=[dw, dh, 40])
            door.apply_translation(dc)
            door.visual.vertex_colors = [170, 140, 110, 255]
            self.meshes.append((door, None, "door"))

    def _build_windows(self):
        for s in self.surfaces:
            if s["category"] != "window": continue
            pid = s.get("parentIdentifier")
            pw = self.smap.get(pid)
            if not pw: continue
            pm = pw["transform"]; sm = s["transform"]
            o = np.array([pm[12], pm[13], pm[14]])
            xa = np.array([pm[0],pm[1],pm[2]])/max(np.linalg.norm([pm[0],pm[1],pm[2]]),1)
            ya = np.array([pm[4],pm[5],pm[6]])/max(np.linalg.norm([pm[4],pm[5],pm[6]]),1)
            za = np.array([pm[8],pm[9],pm[10]])/max(np.linalg.norm([pm[8],pm[9],pm[10]]),1)
            ww, wh = s["dimensions"]["x"], s["dimensions"]["y"]
            wp = tform(sm, 0, 0, 0)
            wl = np.dot(wp - o, xa)
            # 玻璃
            gc = o + xa*(wl + ww/2) + ya*(wp[1] + wh/2) + za*60
            glass = trimesh.primitives.Box(extents=[ww-40, wh-40, 10])
            glass.apply_translation(gc)
            glass.visual.vertex_colors = [200, 220, 240, 200]
            self.meshes.append((glass, None, "window"))

    def _build_floors(self):
        for rm in self.rooms_data:
            for sid in rm.get("surfaces", []):
                s = self.smap.get(sid)
                if s and s["category"] == "floor":
                    m = s["transform"]
                    o = np.array([m[12], 5, m[14]])  # 略高于0
                    xa = np.array([m[0],0,m[2]])/max(np.linalg.norm([m[0],0,m[2]]),1)
                    za = np.array([m[8],0,m[10]])/max(np.linalg.norm([m[8],0,m[10]]),1)
                    fw, fd = s["dimensions"]["x"], s["dimensions"]["y"]
                    fc = o + xa*(fw/2) + za*(fd/2)
                    floor = trimesh.primitives.Box(extents=[fw, 30, fd])
                    floor.apply_translation(fc)
                    floor.visual.vertex_colors = [180, 160, 130, 255]
                    self.meshes.append((floor, rm.get("displayName"), "floor"))
                    break

    def _build_beams_columns(self):
        for s in self.surfaces:
            if s["category"] == "beam":
                m = s["transform"]; p = tform(m,0,0,0)
                w = s["dimensions"]["x"]; h = s["dimensions"].get("y",w)
                b = trimesh.primitives.Box(extents=[w,h,w])
                b.apply_translation([p[0], p[1]+h/2, p[2]])
                b.visual.vertex_colors = [170,170,170,255]
                self.meshes.append((b, None, "beam"))
            elif s["category"] == "column":
                m = s["transform"]; p = tform(m,0,0,0)
                sz = s["dimensions"]["x"]
                c = trimesh.primitives.Box(extents=[sz,2800,sz])
                c.apply_translation([p[0],1400,p[2]])
                c.visual.vertex_colors = [170,170,170,255]
                self.meshes.append((c, None, "column"))

    def export_glb(self, path):
        """导出 GLB + HTML 查看器"""
        combined = trimesh.util.concatenate([m for m,_,_ in self.meshes])
        combined.export(path, file_type="glb")

        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>全房3D模型</title>
<style>body{{margin:0;overflow:hidden;font-family:'Microsoft YaHei',sans-serif;background:#f0f0f0}}
#info{{position:absolute;bottom:20px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.7);
color:#fff;padding:10px 24px;border-radius:20px;font-size:14px;pointer-events:none;z-index:10}}</style></head>
<body><div id="info"> 鼠标拖拽旋转 · 滚轮缩放 · 右键平移 </div>
<script type="importmap">{{"imports":{{"three":"https://unpkg.com/three@0.160.0/build/three.module.js",
"three/addons/":"https://unpkg.com/three@0.160.0/examples/jsm/"}}}}</script>
<script type="module">
import*as THREE from 'three';import{{OrbitControls}}from'three/addons/controls/OrbitControls.js';
import{{GLTFLoader}}from'three/addons/loaders/GLTFLoader.js';
const s=new THREE.Scene();s.background=new THREE.Color(0xf0f0f0);
const c=new THREE.PerspectiveCamera(45,innerWidth/innerHeight,1,100000);
c.position.set(8000,6000,8000);
const r=new THREE.WebGLRenderer({{antialias:true}});r.setSize(innerWidth,innerHeight);r.shadowMap.enabled=true;
document.body.appendChild(r.domElement);
const o=new OrbitControls(c,r.domElement);o.target.set(5000,1400,4000);o.update();
const dl=new THREE.DirectionalLight(0xffffff,1);dl.position.set(5000,5000,5000);s.add(dl);
s.add(new THREE.AmbientLight(0x808080,0.5));
const g=new THREE.GridHelper(20000,20,0x888888,0xcccccc);g.position.set(5000,0,4000);s.add(g);
const l=new GLTFLoader();
const d=atob('{b64}');
const b=new Blob([new Uint8Array([...d].map(c=>c.charCodeAt(0)))],{{type:'model/gltf-binary'}});
l.load(URL.createObjectURL(b),function(g){{s.add(g.scene);
const bx=new THREE.Box3().setFromObject(g.scene);
const ct=bx.getCenter(new THREE.Vector3());o.target.copy(ct);
c.position.set(ct.x+5000,ct.y+3000,ct.z+5000);o.update();}});
addEventListener('resize',()=>{{c.aspect=innerWidth/innerHeight;c.updateProjectionMatrix();r.setSize(innerWidth,innerHeight);}});
(function a(){{requestAnimationFrame(a);o.update();r.render(s,c);}})();
</script></body></html>"""

        html_path = path.replace(".glb", ".html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        print("GLB:", path, os.path.getsize(path), "bytes")
        print("HTML:", html_path)
        print("Faces:", len(combined.faces), "Verts:", len(combined.vertices))
        return combined

    def get_room_areas(self):
        """从场景算每个房间的面积"""
        areas = {}
        for rm in self.rooms_data:
            name = rm.get("displayName", "")
            dims = rm.get("dimensions", {})
            w = dims.get("x", 0) / 1000
            h = dims.get("y", 0) / 1000
            areas[name] = round(w * h, 2)
        return areas

    def get_total_wall_area(self):
        """计算所有墙面的总面积(m2)"""
        total = 0
        for mesh, _, typ in self.meshes:
            if typ == "wall":
                total += mesh.area
        return round(total, 2)

    def generate_floor_plan_dxf(self, dxf_path):
        """从3D模型正交投影生成平面图 DXF"""
        import ezdxf
        from ezdxf.enums import TextEntityAlignment

        doc = ezdxf.new("R2010")
        msp = doc.modelspace()

        # 图层
        for ln, c in [("墙线", 7), ("门窗", 5), ("标注", 2), ("房间名", 6)]:
            doc.layers.add(ln, dxfattribs={"color": c, "lineweight": 35})

        # 收集所有墙在 XZ 平面上的投影
        for mesh, _, typ in self.meshes:
            if typ not in ("wall", "door", "window"):
                continue
            verts = mesh.vertices
            # 提取顶部和底部的边 (Y=0 或 Y=height)
            for i in range(0, len(verts), 4):
                if i+3 < len(verts):
                    v1, v2 = verts[i], verts[i+2]
                    # 只画 XZ 平面
                    msp.add_line((v1[0], v1[2]), (v2[0], v2[2]),
                                dxfattribs={"layer": "墙线" if typ == "wall" else "门窗"})

        # 房间标签
        for rm in self.rooms_data:
            name = rm.get("displayName", "")
            dims = rm.get("dimensions", {})
            w, h = dims.get("x", 0), dims.get("y", 0)
            # 粗略定位
            cx, cz = 2000, 2000
            msp.add_text("%s %d×%d" % (name, w, h), height=300,
                        dxfattribs={"layer": "房间名"}).set_placement(
                            (cx, cz), align=TextEntityAlignment.CENTER)

        doc.saveas(dxf_path)
        print("DXF:", dxf_path)


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "templates/real_apartment.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "templates/real_output/全房模型.glb"
    cond = sys.argv[3] if len(sys.argv) > 3 else "templates/real_output/设计条件.json"

    os.makedirs(os.path.dirname(out), exist_ok=True)

    scene = Scene3D(inp, cond if os.path.exists(cond) else None)
    scene.export_glb(out)
    print()
    print("房间面积:", scene.get_room_areas())
    print("墙面总面积: %.2f m2" % scene.get_total_wall_area())
