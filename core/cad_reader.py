"""
CAD 图纸读取器 v2 - 含拓扑分析
从 DXF 提取墙体 → 合并共线线段 → 检测房间闭环
"""
import os, math, tempfile
from collections import defaultdict

os.environ.setdefault("XDG_CACHE_HOME", os.path.join(tempfile.gettempdir(), "designer_ai_tools_cache"))

import ezdxf


def read_dxf_floor_plan(dxf_path: str) -> dict:
    """读取 DXF 文件，提取可识别的建筑元素"""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    walls = []
    doors = []
    windows = []
    texts = []
    all_points = []

    WALL_KEYWORDS = ['墙', 'wall', 'WALL', '结构']
    DOOR_KEYWORDS = ['门', 'door', 'DOOR']
    WINDOW_KEYWORDS = ['窗', 'window', 'WINDOW']

    def _match_layer(layer_name, keywords):
        return any(kw in layer_name for kw in keywords)

    def _add_segment(layer, x1, y1, x2, y2):
        all_points.extend([(x1, y1), (x2, y2)])
        if _match_layer(layer, WALL_KEYWORDS):
            walls.append((x1, y1, x2, y2, 120))
        elif _match_layer(layer, DOOR_KEYWORDS):
            doors.append((x1, y1, x2, y2))
        elif _match_layer(layer, WINDOW_KEYWORDS):
            windows.append((x1, y1, x2, y2))
        else:
            length = math.hypot(x2 - x1, y2 - y1)
            if length > 500:
                walls.append((x1, y1, x2, y2, 120))

    for entity in msp:
        dxf = entity.dxf
        layer = dxf.layer if hasattr(dxf, 'layer') else ''

        if entity.dxftype() == 'LINE':
            x1, y1 = dxf.start.x, dxf.start.y
            x2, y2 = dxf.end.x, dxf.end.y
            _add_segment(layer, x1, y1, x2, y2)

        elif entity.dxftype() == 'LWPOLYLINE':
            pts = list(entity.get_points('xy'))
            segment_count = len(pts) if entity.closed else len(pts) - 1
            for i in range(max(0, segment_count)):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % len(pts)]
                _add_segment(layer, x1, y1, x2, y2)

        elif entity.dxftype() in ('TEXT', 'MTEXT'):
            text = entity.plain_text() if hasattr(entity, 'plain_text') else dxf.text
            texts.append({
                "text": text,
                "x": dxf.insert.x if hasattr(dxf, 'insert') else 0,
                "y": dxf.insert.y if hasattr(dxf, 'insert') else 0,
                "height": dxf.height if hasattr(dxf, 'height') else 20,
                "layer": layer,
            })

    if all_points:
        min_x = min(p[0] for p in all_points)
        min_y = min(p[1] for p in all_points)
        max_x = max(p[0] for p in all_points)
        max_y = max(p[1] for p in all_points)
    else:
        min_x = min_y = max_x = max_y = 0

    layers = [layer.dxf.name for layer in doc.layers]

    return {
        "walls": walls,
        "doors": doors,
        "windows": windows,
        "texts": texts,
        "bounds": (min_x, min_y, max_x, max_y),
        "layers": layers,
        "total_lines": len(walls) + len(doors) + len(windows),
        "wall_count": len(walls),
        "door_count": len(doors),
        "window_count": len(windows),
        "source": dxf_path,
    }


def merge_collinear_walls(walls: list, tolerance_mm: float = 10) -> list:
    """
    合并共线且重叠/相邻的墙段。
    输入: [(x1,y1,x2,y2,thickness), ...]
    输出: 合并后的墙段列表
    """
    if not walls:
        return []

    # 将墙段归一化为 (start, end, thickness)，start < end
    normalized = []
    for x1, y1, x2, y2, t in walls:
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        ux, uy = dx / length, dy / length
        if (x1, y1) < (x2, y2):
            normalized.append((x1, y1, x2, y2, ux, uy, length, t))
        else:
            normalized.append((x2, y2, x1, y1, -ux, -uy, length, t))

    # 按方向分组
    groups = []
    used = [False] * len(normalized)
    for i, (sx1, sy1, ex1, ey1, ux1, uy1, l1, t1) in enumerate(normalized):
        if used[i]:
            continue
        group = [i]
        for j in range(i + 1, len(normalized)):
            if used[j]:
                continue
            sx2, sy2, ex2, ey2, ux2, uy2, l2, t2 = normalized[j]
            # 方向相同或相反
            dot = ux1 * ux2 + uy1 * uy2
            if abs(abs(dot) - 1) < 0.01:
                # 检查是否共线
                # 投影距离
                proj = (sx2 - sx1) * ux1 + (sy2 - sy1) * uy1
                dist = math.hypot((sx2 - sx1) - proj * ux1, (sy2 - sy1) - proj * uy1)
                if dist < tolerance_mm:
                    group.append(j)

        groups.append(group)
        for j in group:
            used[j] = True

    # 合并每组
    merged = []
    for group in groups:
        t = normalized[group[0]][7]  # 取第一个的厚度
        # 收集所有点在方向上的投影
        projections = []
        for i in group:
            sx, sy, ex, ey, ux, uy, l, _ = normalized[i]
            proj_s = sx * ux + sy * uy
            proj_e = ex * ux + ey * uy
            projections.append(min(proj_s, proj_e))
            projections.append(max(proj_s, proj_e))

        min_p = min(projections)
        max_p = max(projections)
        ux, uy = normalized[group[0]][4], normalized[group[0]][5]
        x1 = min_p * ux
        y1 = min_p * uy
        x2 = max_p * ux
        y2 = max_p * uy

        # 找到投影原点
        sx0, sy0 = normalized[group[0]][0], normalized[group[0]][1]
        # 重建端点
        ref = sx0 * ux + sy0 * uy
        ox = sx0 - ref * ux
        oy = sy0 - ref * uy
        x1 = ox + min_p * ux
        y1 = oy + min_p * uy
        x2 = ox + max_p * ux
        y2 = oy + max_p * uy

        merged.append((x1, y1, x2, y2, t))

    return merged


def detect_rooms_from_walls(walls: list, texts: list = None, max_dimension_mm: float = 50000) -> list:
    """
    从墙线检测房间闭环。
    使用图论: 建邻接图 → DFS 找最小环 → 过滤房间大小

    Args:
        walls: [(x1,y1,x2,y2,thickness), ...]
        texts: [{"text":..., "x":..., "y":...}, ...]

    Returns:
        [{"name": str, "floor_points": [(x,y),...], "area_m2": float}, ...]
    """
    if len(walls) < 3:
        return []

    texts = texts or []

    # 合并共线墙段
    merged = merge_collinear_walls(walls)

    # 建端点邻接图
    SNAP = 50  # mm 容差
    graph = defaultdict(list)  # (x,y) → [(nx,ny, wall_idx)]

    def snap(x, y):
        return (round(x / SNAP) * SNAP, round(y / SNAP) * SNAP)

    for idx, (x1, y1, x2, y2, t) in enumerate(merged):
        s1 = snap(x1, y1)
        s2 = snap(x2, y2)
        graph[s1].append((s2, idx))
        graph[s2].append((s1, idx))

    # DFS 找最小闭环
    rooms = []
    visited_edges = set()

    for start in graph:
        if len(graph[start]) < 2:
            continue

        # DFS 从 start 出发找环
        def find_cycle(node, path_nodes, path_edges, depth):
            if depth > 30:  # 防止无限递归
                return None
            for neighbor, edge_idx in graph[node]:
                if edge_idx in path_edges:
                    continue
                if neighbor == start and depth >= 2:
                    # 找到环
                    new_edges = path_edges + [edge_idx]
                    # 检查是否有重复边
                    if len(set(new_edges)) < len(new_edges):
                        continue
                    return path_nodes + [neighbor], new_edges
                if neighbor in path_nodes:
                    continue
                result = find_cycle(neighbor, path_nodes + [neighbor],
                                    path_edges + [edge_idx], depth + 1)
                if result:
                    return result
            return None

        result = find_cycle(start, [start], [], 0)
        if result and len(result[0]) >= 3:
            nodes, edges = result
            # 计算面积
            pts = nodes[:-1]  # 去最后一个重复点
            if len(pts) < 3:
                continue
            area = 0
            n = len(pts)
            for i in range(n):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % n]
                area += x1 * y2 - x2 * y1
            area_m2 = abs(area) / 2e6

            # 过滤: 1~500m2
            if 0.5 < area_m2 < 500:
                # 检查边集合是否已使用
                edge_key = tuple(sorted(edges))
                if edge_key not in visited_edges:
                    visited_edges.add(edge_key)
                    rooms.append({
                        "name": _find_room_name(pts, texts),
                        "floor_points": [{"x": p[0], "y": p[1]} for p in pts],
                        "area_m2": round(area_m2, 2),
                        "perimeter_m": round(sum(
                            math.hypot(pts[i][0] - pts[(i+1)%n][0],
                                      pts[i][1] - pts[(i+1)%n][1])
                            for i in range(n)) / 1000, 2),
                    })

    # 按面积排序
    rooms.sort(key=lambda r: r["area_m2"], reverse=True)
    return rooms


def _find_room_name(points, texts):
    """从最近文字标注找房间名"""
    if not texts:
        return ""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    best = ""
    best_dist = float("inf")
    room_keywords = ["客厅", "餐厅", "卧室", "厨房", "卫生间", "书房",
                     "阳台", "玄关", "储物", "衣帽", "走廊", "主卧", "次卧",
                     "living", "bedroom", "kitchen", "bathroom"]
    for t in texts:
        txt = t.get("text", "")
        if not txt:
            continue
        # 优先匹配房间名关键词
        if any(k in txt for k in room_keywords):
            dx = t["x"] - cx
            dy = t["y"] - cy
            dist = math.hypot(dx, dy)
            if dist < best_dist:
                best_dist = dist
                best = txt
    return best


def read_dxf_with_rooms(dxf_path: str) -> dict:
    """
    读取 DXF 并分析房间拓扑
    Returns: 与 read_dxf_floor_plan 兼容的 dict，额外包含 detected_rooms
    """
    data = read_dxf_floor_plan(dxf_path)
    rooms = detect_rooms_from_walls(data["walls"], data["texts"])
    data["detected_rooms"] = rooms
    return data
