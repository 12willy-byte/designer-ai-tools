"""
Scene3D → GLTF 2.0 导出器
将 3D 场景导出为 glTF 格式，可导入 Blender/Three.js/Unity 等
"""
import os, sys, json, struct, base64, math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene3d import Scene3D, Wall, Room, Furniture, Beam, Column, OpeningType, Point3D


class GLTFExporter:
    """将 Scene3D 导出为 glTF 2.0 (GLB 格式)"""
    
    def __init__(self, scene: Scene3D):
        self.scene = scene
        self.nodes = []
        self.meshes = []
        self.accessors = []
        self.bufferViews = []
        self.materials = []
        self.buffer_data = bytearray()
        self.node_idx = 0
        
        # Default material indices
        self._add_material("wall", (0.50, 0.56, 0.63, 1.0), 0.7, 0.05)
        self._add_material("floor", (0.84, 0.81, 0.75, 1.0), 0.8, 0.0)
        self._add_material("door", (0.91, 0.57, 0.23, 1.0), 0.5, 0.1)
        self._add_material("window", (0.29, 0.56, 0.85, 0.5), 0.2, 0.3)
        self._add_material("furniture", (0.79, 0.66, 0.43, 1.0), 0.6, 0.05)
        self._add_material("beam", (1.0, 0.84, 0.0, 0.4), 0.4, 0.2)
        self._add_material("column", (0.55, 0.27, 0.07, 1.0), 0.3, 0.3)
    
    def _add_material(self, name, color, roughness, metallic):
        self.materials.append({
            "pbrMetallicRoughness": {
                "baseColorFactor": list(color),
                "metallicFactor": metallic,
                "roughnessFactor": roughness,
            },
            "name": name,
            "alphaMode": "BLEND" if color[3] < 1.0 else "OPAQUE",
        })
        return len(self.materials) - 1
    
    def _pad_to_4(self):
        while len(self.buffer_data) % 4 != 0:
            self.buffer_data.append(0)
    
    def _add_box_mesh(self, w, h, d, material_idx, transform=None):
        """添加盒子网格 (单位: 米)"""
        hw, hh, hd = w/2, h/2, d/2
        # 36 vertices (6 faces * 2 triangles * 3 vertices) with normals
        # Using interleaved: position(3) + normal(3) = 6 floats per vertex
        verts = []
        # +Y face (top)
        verts.extend([-hw, hh, -hd, 0,1,0,  hw, hh, -hd, 0,1,0,  hw, hh, hd, 0,1,0])
        verts.extend([-hw, hh, -hd, 0,1,0,  hw, hh, hd, 0,1,0, -hw, hh, hd, 0,1,0])
        # -Y face (bottom)
        verts.extend([-hw, -hh, hd, 0,-1,0,  hw, -hh, hd, 0,-1,0,  hw, -hh, -hd, 0,-1,0])
        verts.extend([-hw, -hh, hd, 0,-1,0,  hw, -hh, -hd, 0,-1,0, -hw, -hh, -hd, 0,-1,0])
        # +X face
        verts.extend([hw, -hh, hd, 1,0,0,  hw, hh, hd, 1,0,0,  hw, hh, -hd, 1,0,0])
        verts.extend([hw, -hh, hd, 1,0,0,  hw, hh, -hd, 1,0,0,  hw, -hh, -hd, 1,0,0])
        # -X face
        verts.extend([-hw, -hh, -hd, -1,0,0, -hw, hh, -hd, -1,0,0, -hw, hh, hd, -1,0,0])
        verts.extend([-hw, -hh, -hd, -1,0,0, -hw, hh, hd, -1,0,0, -hw, -hh, hd, -1,0,0])
        # +Z face
        verts.extend([-hw, -hh, hd, 0,0,1, -hw, hh, hd, 0,0,1,  hw, hh, hd, 0,0,1])
        verts.extend([-hw, -hh, hd, 0,0,1,  hw, hh, hd, 0,0,1,  hw, -hh, hd, 0,0,1])
        # -Z face
        verts.extend([hw, -hh, -hd, 0,0,-1, hw, hh, -hd, 0,0,-1, -hw, hh, -hd, 0,0,-1])
        verts.extend([hw, -hh, -hd, 0,0,-1, -hw, hh, -hd, 0,0,-1, -hw, -hh, -hd, 0,0,-1])
        
        vert_bytes = struct.pack(f'<{len(verts)}f', *verts)
        self._pad_to_4()
        bv_offset = len(self.buffer_data)
        self.buffer_data.extend(vert_bytes)
        
        bv = {
            "buffer": 0, "byteOffset": bv_offset, "byteLength": len(vert_bytes),
            "target": 34962  # ARRAY_BUFFER
        }
        bv_idx = len(self.bufferViews)
        self.bufferViews.append(bv)
        
        # Accessor
        acc = {
            "bufferView": bv_idx, "componentType": 5126, "count": 36,
            "type": "VEC3", "byteOffset": 0,
            "min": [-hw, -hh, -hd], "max": [hw, hh, hd],
        }
        pos_acc_idx = len(self.accessors)
        self.accessors.append(dict(acc))
        
        # Normals accessor (offset by 12 bytes = 3 floats)
        norm_acc = dict(acc)
        norm_acc["byteOffset"] = 12
        norm_acc["min"] = [-1,-1,-1]
        norm_acc["max"] = [1,1,1]
        norm_acc_idx = len(self.accessors)
        self.accessors.append(norm_acc)
        
        mesh = {
            "primitives": [{
                "attributes": {"POSITION": pos_acc_idx, "NORMAL": norm_acc_idx},
                "material": material_idx,
            }],
            "name": f"box_{w:.2f}x{h:.2f}x{d:.2f}",
        }
        mesh_idx = len(self.meshes)
        self.meshes.append(mesh)
        
        node = {"mesh": mesh_idx, "name": mesh["name"]}
        if transform:
            node["matrix"] = transform
        node_idx = len(self.nodes)
        self.nodes.append(node)
        return node_idx
    
    def _add_plane_mesh(self, vertices_2d, y, material_idx):
        """添加平面网格 (用于地面)"""
        verts = []
        indices = []
        n = len(vertices_2d)
        if n < 3:
            return -1
        
        # Fan triangulation from centroid
        cx = sum(v[0] for v in vertices_2d) / n
        cz = sum(v[1] for v in vertices_2d) / n
        
        # Vertices (position + normal)
        for i in range(n):
            verts.extend([vertices_2d[i][0], y, vertices_2d[i][1], 0, 1, 0])
        
        # Indices
        for i in range(n):
            j = (i + 1) % n
            indices.extend([i, j, n])  # n will be centroid
        
        # Add centroid vertex
        verts.extend([cx, y, cz, 0, 1, 0])
        
        # Convert to interleaved + indexed
        # For simplicity, duplicate vertices per triangle
        tri_verts = []
        for t in range(0, len(indices), 3):
            for k in range(3):
                vi = indices[t + k]
                base = vi * 6
                tri_verts.extend(verts[base:base+6])
        
        vert_bytes = struct.pack(f'<{len(tri_verts)}f', *tri_verts)
        self._pad_to_4()
        bv_offset = len(self.buffer_data)
        self.buffer_data.extend(vert_bytes)
        
        bv = {"buffer": 0, "byteOffset": bv_offset, "byteLength": len(vert_bytes), "target": 34962}
        bv_idx = len(self.bufferViews)
        self.bufferViews.append(bv)
        
        vcount = len(tri_verts) // 6
        pos_acc = {"bufferView": bv_idx, "componentType": 5126, "count": vcount, "type": "VEC3", "byteOffset": 0,
                   "min": [min(v[0] for v in vertices_2d), y, min(v[1] for v in vertices_2d)],
                   "max": [max(v[0] for v in vertices_2d), y, max(v[1] for v in vertices_2d)]}
        pos_idx = len(self.accessors)
        self.accessors.append(pos_acc)
        norm_acc = dict(pos_acc)
        norm_acc["byteOffset"] = 12
        norm_acc["min"] = [0,1,0]; norm_acc["max"] = [0,1,0]
        norm_idx = len(self.accessors)
        self.accessors.append(norm_acc)
        
        mesh = {"primitives": [{"attributes": {"POSITION": pos_idx, "NORMAL": norm_idx}, "material": material_idx}]}
        mesh_idx = len(self.meshes)
        self.meshes.append(mesh)
        node = {"mesh": mesh_idx, "name": "floor"}
        node_idx = len(self.nodes)
        self.nodes.append(node)
        return node_idx
    
    def export(self, output_path: str) -> str:
        """导出为 .glb 文件"""
        scene = self.scene
        root_children = []
        
        # 地面
        for room in scene.rooms.values():
            if len(room.floor_points) >= 3:
                pts_2d = [(p.x / 1000, p.z / 1000) for p in room.floor_points]
                ni = self._add_plane_mesh(pts_2d, 0.01, 1)  # floor material
                if ni >= 0:
                    root_children.append(ni)
        
        # 墙体
        wall_mat = 0
        door_mat = 2
        window_mat = 3
        for wall in scene.walls.values():
            dx, dz = wall.direction
            nx, nz = -dz, dx
            half_t = wall.thickness_mm / 2000  # half thickness in meters
            x1, z1 = wall.start.x / 1000, wall.start.z / 1000
            wall_len = wall.length_mm / 1000
            wall_h = wall.height_mm / 1000
            
            segs = wall.opening_segments()
            for s, e in segs:
                seg_len = (e - s) / 1000
                if seg_len < 0.01:
                    continue
                cx = x1 + dx * (s/1000 + seg_len/2)
                cz = z1 + dz * (s/1000 + seg_len/2)
                # Rotation matrix for wall orientation
                cos_a, sin_a = dx, dz
                matrix = [
                    cos_a, 0, -sin_a, 0,
                    0, 1, 0, 0,
                    sin_a, 0, cos_a, 0,
                    cx, wall_h/2, cz, 1,
                ]
                ni = self._add_box_mesh(seg_len, wall_h, wall.thickness_mm/1000, wall_mat, matrix)
                root_children.append(ni)
            
            # 门窗
            for op in wall.openings:
                ocx = x1 + dx * (op.offset_mm + op.width_mm/2) / 1000
                ocz = z1 + dz * (op.offset_mm + op.width_mm/2) / 1000
                oh = op.height_mm / 1000
                ow = op.width_mm / 1000
                is_door = op.type == OpeningType.DOOR
                mat = door_mat if is_door else window_mat
                oy = oh/2 if is_door else (op.sill_height_mm/1000 + oh/2)
                matrix = [dx, 0, -dz, 0, 0, 1, 0, 0, dz, 0, dx, 0, ocx, oy, ocz, 1]
                ni = self._add_box_mesh(ow, oh, wall.thickness_mm/1000*1.1, mat, matrix)
                root_children.append(ni)
        
        # 家具
        furn_mat = 4
        for furn in scene.furniture.values():
            fw = furn.width_mm / 1000
            fd = furn.depth_mm / 1000
            fh = furn.height_mm / 1000
            px = furn.position.x / 1000 + fw/2
            pz = furn.position.z / 1000 + fd/2
            matrix = [1,0,0,0, 0,1,0,0, 0,0,1,0, px,fh/2,pz,1]
            ni = self._add_box_mesh(fw, fh, fd, furn_mat, matrix)
            root_children.append(ni)
        
        # 梁
        beam_mat = 5
        for beam in scene.beams.values():
            bw = beam.width_mm / 1000
            bd = beam.depth_mm / 1000
            bl = beam.length_mm / 1000
            px = beam.position.x / 1000 + bl/2
            py = beam.position.y / 1000 + bd/2
            pz = beam.position.z / 1000 + bw/2
            matrix = [1,0,0,0, 0,1,0,0, 0,0,1,0, px,py,pz,1]
            ni = self._add_box_mesh(bl, bd, bw, beam_mat, matrix)
            root_children.append(ni)
        
        # 柱
        col_mat = 6
        for col in scene.columns.values():
            cw = col.width_mm / 1000
            cd = col.depth_mm / 1000
            ch = col.height_mm / 1000
            px = col.position.x / 1000 + cw/2
            py = col.position.y / 1000 + ch/2
            pz = col.position.z / 1000 + cd/2
            matrix = [1,0,0,0, 0,1,0,0, 0,0,1,0, px,py,pz,1]
            ni = self._add_box_mesh(cw, ch, cd, col_mat, matrix)
            root_children.append(ni)
        
        # 构建 GLTF JSON
        gltf = {
            "asset": {"version": "2.0", "generator": "设计师AI工具 GLTFExporter"},
            "scene": 0,
            "scenes": [{"nodes": root_children, "name": scene.name or "Scene"}],
            "nodes": self.nodes,
            "meshes": self.meshes,
            "accessors": self.accessors,
            "bufferViews": self.bufferViews,
            "materials": self.materials,
            "buffers": [{"byteLength": len(self.buffer_data)}],
        }
        
        # 写入 GLB
        gltf_json = json.dumps(gltf, ensure_ascii=False).encode('utf-8')
        # Pad JSON to 4-byte alignment
        while len(gltf_json) % 4 != 0:
            gltf_json += b' '
        
        # GLB header: magic, version, length
        total_len = 12 + 8 + len(gltf_json) + 8 + len(self.buffer_data)
        header = struct.pack('<I', 0x46546C67)  # magic 'glTF'
        header += struct.pack('<I', 2)           # version 2
        header += struct.pack('<I', total_len)   # total length
        
        # JSON chunk
        json_chunk = struct.pack('<I', len(gltf_json))
        json_chunk += struct.pack('<I', 0x4E4F534A)  # 'JSON'
        json_chunk += gltf_json
        
        # BIN chunk
        bin_chunk = struct.pack('<I', len(self.buffer_data))
        bin_chunk += struct.pack('<I', 0x004E4942)  # 'BIN\0'
        bin_chunk += bytes(self.buffer_data)
        
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(header + json_chunk + bin_chunk)
        
        return output_path


def export_scene_to_gltf(scene: Scene3D, output_path: str) -> str:
    """便捷函数: Scene3D → GLB"""
    exporter = GLTFExporter(scene)
    return exporter.export(output_path)
