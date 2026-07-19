"""
3D 透视渲染器 - Scene3D -> 白模透视 PNG
用于 AI 效果图生成的结构输入 (ControlNet / img2img)
"""
import os, sys, math
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection, Line3DCollection
import matplotlib.patheffects as pe

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.scene3d import Scene3D, OpeningType


def render_perspective(scene, output_path, camera_pos=None, camera_target=None,
                       resolution=1024, style='white_model'):
    """
    渲染 3D 透视白模图

    Args:
        scene: Scene3D
        output_path: PNG 输出路径
        camera_pos: (x, y, z) 相机位置 (m)
        camera_target: (x, y, z) 看向目标 (m)
        resolution: 分辨率
        style: 'white_model' | 'edge_only'
    """
    fig = plt.figure(figsize=(resolution/100, resolution/100), dpi=100)
    ax = fig.add_subplot(111, projection='3d')
    ax.set_facecolor('white')

    # 收集所有几何体
    polygons = []   # (vertices_3d, facecolor, edgecolor, alpha, label)
    lines = []      # (start, end, color, lw)

    # 墙
    for wall in scene.walls.values():
        dx, dz = wall.direction
        nx, nz = -dz, dx
        half_t = wall.thickness_mm / 2000
        x1, z1 = wall.start.x / 1000, wall.start.z / 1000
        wh = wall.height_mm / 1000
        segs = wall.opening_segments()

        for s, e in segs:
            slen = (e - s) / 1000
            if slen < 0.01:
                continue
            sx = x1 + dx * s / 1000
            sz = z1 + dz * s / 1000
            ex = sx + dx * slen
            ez = sz + dz * slen
            # 8 个顶点
            v = [
                [sx + nx*half_t, 0, sz + nz*half_t],
                [ex + nx*half_t, 0, ez + nz*half_t],
                [ex - nx*half_t, 0, ez - nz*half_t],
                [sx - nx*half_t, 0, sz - nz*half_t],
                [sx + nx*half_t, wh, sz + nz*half_t],
                [ex + nx*half_t, wh, ez + nz*half_t],
                [ex - nx*half_t, wh, ez - nz*half_t],
                [sx - nx*half_t, wh, sz - nz*half_t],
            ]
            # 6 个面
            faces = [
                [v[0],v[1],v[5],v[4]],  # front
                [v[2],v[3],v[7],v[6]],  # back
                [v[0],v[3],v[7],v[4]],  # left
                [v[1],v[2],v[6],v[5]],  # right
                [v[4],v[5],v[6],v[7]],  # top
            ]
            for face in faces:
                if style == 'edge_only':
                    for i in range(len(face)):
                        lines.append((face[i], face[(i+1)%len(face)], '#333333', 1))
                else:
                    polygons.append((face, '#e8e0d5', '#b0a090', 1.0, 'wall'))

        # 开口
        for op in wall.openings:
            ocx = x1 + dx * (op.offset_mm + op.width_mm/2) / 1000
            ocz = z1 + dz * (op.offset_mm + op.width_mm/2) / 1000
            ow = op.width_mm / 1000
            oh = op.height_mm / 1000
            oy = oh/2 if op.type == OpeningType.DOOR else (op.sill_height_mm/1000 + oh/2)

    # 地面
    for room in scene.rooms.values():
        if len(room.floor_points) >= 3:
            pts = [[p.x/1000, 0.001, p.z/1000] for p in room.floor_points]
            polygons.append((pts, '#f5f0e8', '#ccc', 0.9, 'floor'))

    # 家具
    for furn in scene.furniture.values():
        px, pz = furn.position.x/1000, furn.position.z/1000
        fw, fd, fh = furn.width_mm/1000, furn.depth_mm/1000, furn.height_mm/1000
        v = [
            [px, 0, pz], [px+fw, 0, pz], [px+fw, 0, pz+fd], [px, 0, pz+fd],
            [px, fh, pz], [px+fw, fh, pz], [px+fw, fh, pz+fd], [px, fh, pz+fd],
        ]
        faces = [
            [v[0],v[1],v[5],v[4]], [v[2],v[3],v[7],v[6]],
            [v[0],v[3],v[7],v[4]], [v[1],v[2],v[6],v[5]], [v[4],v[5],v[6],v[7]],
        ]
        for face in faces:
            polygons.append((face, '#d4c4a0', '#b0a080', 1.0, 'furniture'))

    # 绘制
    for verts, fc, ec, alpha, label in polygons:
        poly = Poly3DCollection([verts], alpha=alpha, facecolor=fc, edgecolor=ec,
                                linewidths=0.5)
        ax.add_collection3d(poly)

    # 计算场景中心
    all_x, all_z = [], []
    for wall in scene.walls.values():
        all_x.extend([wall.start.x/1000, wall.end.x/1000])
        all_z.extend([wall.start.z/1000, wall.end.z/1000])
    if not all_x:
        all_x, all_z = [0, 5], [0, 5]
    cx, cz = sum(all_x)/len(all_x), sum(all_z)/len(all_z)
    span = max(max(all_x)-min(all_x), max(all_z)-min(all_z), 5)

    # 相机
    if camera_pos is None:
        camera_pos = (cx + span*0.8, span*0.7, cz + span*0.8)
    if camera_target is None:
        camera_target = (cx, 1.4, cz)

    # 设置视角
    ax.view_init(elev=25, azim=-45)
    ax.set_xlim(cx - span, cx + span)
    ax.set_ylim(0, 3.5)
    ax.set_zlim(cz - span, cz + span)
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_zlabel('Z (m)')
    ax.set_title('3D Perspective - White Model')

    # 等比例
    ax.set_box_aspect([1, 0.6, 1])

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    return output_path


def render_top_view(scene, output_path, resolution=1024):
    """渲染俯视图 (正交)"""
    fig, ax = plt.subplots(figsize=(resolution/100, resolution/100), dpi=100)
    ax.set_facecolor('white')
    ax.set_aspect('equal')

    # 墙
    for wall in scene.walls.values():
        dx, dz = wall.direction
        nx, nz = -dz, dx
        half_t = wall.thickness_mm / 2000
        x1, z1 = wall.start.x/1000, wall.start.z/1000
        segs = wall.opening_segments()
        for s, e in segs:
            slen = (e-s)/1000
            if slen < 0.01: continue
            sx = x1 + dx*s/1000
            sz = z1 + dz*s/1000
            rect = plt.Rectangle((sx+nx*half_t, sz+nz*half_t), slen*dx-slen*dx+dx*slen if abs(dx)>0.01 else wall.thickness_mm/1000,
                                wall.thickness_mm/1000, facecolor='#808080', edgecolor='#333', lw=1)
            # Simplified
            from matplotlib.patches import Polygon
            corners = [
                (sx+nx*half_t, sz+nz*half_t),
                (sx+dx*slen+nx*half_t, sz+dz*slen+nz*half_t),
                (sx+dx*slen-nx*half_t, sz+dz*slen-nz*half_t),
                (sx-nx*half_t, sz-nz*half_t),
            ]
            ax.add_patch(Polygon(corners, facecolor='#c0c0c0', edgecolor='#333', lw=1))

    # 地面
    for room in scene.rooms.values():
        if len(room.floor_points) >= 3:
            pts = [(p.x/1000, p.z/1000) for p in room.floor_points]
            ax.add_patch(Polygon(pts, facecolor='#fafaf5', edgecolor='#ddd', lw=0.5))

    # 家具
    for furn in scene.furniture.values():
        px, pz = furn.position.x/1000, furn.position.z/1000
        fw, fd = furn.width_mm/1000, furn.depth_mm/1000
        ax.add_patch(plt.Rectangle((px, pz), fw, fd, facecolor='#d4c4a0', edgecolor='#b0a080', lw=0.5))

    # 门窗
    for wall in scene.walls.values():
        dx, dz = wall.direction
        x1, z1 = wall.start.x/1000, wall.start.z/1000
        for op in wall.openings:
            ocx = x1 + dx*op.offset_mm/1000 + dx*op.width_mm/2000
            ocz = z1 + dz*op.offset_mm/1000 + dz*op.width_mm/2000
            ow = op.width_mm/1000
            color = '#e8913a' if op.type == OpeningType.DOOR else '#4a90d9'
            ax.plot(ocx, ocz, 's', color=color, markersize=6)

    all_x, all_z = [], []
    for wall in scene.walls.values():
        all_x.extend([wall.start.x/1000, wall.end.x/1000])
        all_z.extend([wall.start.z/1000, wall.end.z/1000])
    if all_x:
        margin = 1
        ax.set_xlim(min(all_x)-margin, max(all_x)+margin)
        ax.set_ylim(min(all_z)-margin, max(all_z)+margin)

    ax.set_title(scene.name or 'Top View')
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    return output_path
