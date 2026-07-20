"""矢量 PDF 毛坯图纸解析器 —— M0 的第三条空间输入路径。

只支持矢量 PDF（CAD 打印/导出的线条图，线条是矢量路径）。
扫描/拍照型图片 PDF 会被明确识别并拒绝：不硬解析、不伪造几何。

比例尺校准（矢量 PDF 的坐标单位是 point = 1/72 英寸，不是毫米）：
1. 调用方显式传入 scale（"1:50" 或 "A3"/"A2" 等图幅反推）——人工事实优先于推断；
2. 图纸中的比例文字（如 "比例 1:50"）；
3. 尺寸标注数字反推（数字文本 ↔ 最近长线段长度，聚类投票）；
4. 全部失败：仍输出几何拓扑，但 dimensions_calibrated=False、
   scale_confidence 低，融合层会压低几何置信度，闸门相应降低放行等级。

输出结构与 cad_reader.read_dxf_with_rooms 兼容（坐标统一换算为 mm，
y 轴向上），可直接作为 cad_plan 进入 space_profile 融合层与自动化闸门。
限制如实写入 limitations，风格对齐 scan_importer。
"""
import math
import os
import re

import pdfplumber

from core.cad_reader import detect_room_faces_from_walls


SCHEMA_VERSION = "pdf_plan.v1"

MM_PER_PT = 25.4 / 72.0  # 纸面上 1pt = 0.3528mm

# 校准阈值（单位 mm）；未校准时坐标仍是 pt，使用 _UNCAL 阈值
_MIN_WALL_MM = 500.0
_GAP_RANGE_MM = (500.0, 2600.0)   # 门窗洞口宽度合理区间
_SNAP_MM = 50.0
_MIN_WALL_UNCAL = 40.0            # ≈11mm 纸面长度
_GAP_RANGE_UNCAL = (25.0, 150.0)
_SNAP_UNCAL = 5.0

_PAPER_SIZES_MM = {  # 横向图幅短边/长边（用于图幅反推）
    "A4": 297.0, "A3": 420.0, "A2": 594.0, "A1": 841.0, "A0": 1189.0,
}

_NUM_MM_RE = re.compile(r"^\d{3,5}$")            # 4200 / 6400
_NUM_M_RE = re.compile(r"^(\d{1,2})\.(\d{3})$")  # 3.600（米）
_SCALE_TEXT_RE = re.compile(r"1\s*[:：]\s*(\d{1,4})")


def read_pdf_plan(pdf_path, scale=None, page_number=0):
    """解析矢量 PDF 毛坯图纸，返回 cad_plan 兼容结构（单位 mm）。

    Args:
        pdf_path: PDF 文件路径
        scale: 可选显式比例尺，"1:50" 样式或 "A3"/"A2" 等图幅
        page_number: 解析第几页（默认第 1 页；多页 PDF 只解析一页）
    """
    base = {
        "schema_version": SCHEMA_VERSION,
        "source": pdf_path,
        "source_type": "pdf_vector",
        "accepted": False,
        "walls": [],
        "doors": [],
        "windows": [],
        "texts": [],
        "bounds": (0, 0, 0, 0),
        "layers": [],
        "total_lines": 0,
        "wall_count": 0,
        "door_count": 0,
        "window_count": 0,
        "detected_rooms": [],
        "outline": None,
        "confidence": 0.0,
        "limitations": [],
        "pdf": {
            "page_count": 0,
            "page_used": page_number,
            "page_size_pt": None,
            "is_vector": False,
            "vector_segment_count": 0,
            "curve_count": 0,
            "image_count": 0,
            "pt_to_mm": None,
            "scale_source": "none",
            "scale_confidence": 0.0,
            "dimensions_calibrated": False,
            "scale_votes": 0,
            "unclassified_segment_count": 0,
        },
    }

    if not os.path.exists(pdf_path):
        base["source_type"] = "pdf_missing"
        base["limitations"].append("PDF 文件不存在。")
        return base

    with pdfplumber.open(pdf_path) as doc:
        base["pdf"]["page_count"] = len(doc.pages)
        if not doc.pages:
            base["source_type"] = "pdf_empty"
            base["limitations"].append("PDF 没有任何页面。")
            return base
        page_number = min(page_number, len(doc.pages) - 1)
        page = doc.pages[page_number]
        segs_pt = _extract_segments(page)
        words_pt = _extract_words(page)
        raw_text = page.extract_text() or ""
        base["pdf"]["curve_count"] = len(page.curves)
        base["pdf"]["image_count"] = len(page.images)
        base["pdf"]["page_size_pt"] = [round(float(page.width), 2), round(float(page.height), 2)]

    base["pdf"]["vector_segment_count"] = len(segs_pt)

    if not segs_pt:
        if base["pdf"]["image_count"]:
            base["source_type"] = "pdf_raster"
            base["limitations"].append(
                "这是图片型（扫描/拍照）PDF：页面只有位图、没有矢量路径，当前不支持解析。"
                "建议改用 CAD/DXF 毛坯图，或使用 RoomPlan 语义扫描。")
        else:
            base["source_type"] = "pdf_empty"
            base["limitations"].append("PDF 页面中既没有矢量路径也没有图片，无法提取图纸信息。")
        return base

    base["pdf"]["is_vector"] = True
    if base["pdf"]["page_count"] > 1:
        base["limitations"].append(
            f"PDF 共 {base['pdf']['page_count']} 页，当前只解析第 {page_number + 1} 页。")
    if base["pdf"]["curve_count"]:
        base["limitations"].append(
            f"图纸包含 {base['pdf']['curve_count']} 条曲线（可能是门弧/符号），已忽略，只按直线段解析。")

    # ---------- 比例尺校准 ----------
    calib = _calibrate_scale(scale, raw_text, words_pt, segs_pt)
    factor = calib["pt_to_mm"]
    calibrated = calib["dimensions_calibrated"]
    base["pdf"].update({
        "pt_to_mm": round(factor, 6),
        "scale_source": calib["scale_source"],
        "scale_confidence": calib["scale_confidence"],
        "dimensions_calibrated": calibrated,
        "scale_votes": calib["scale_votes"],
    })
    base["limitations"].extend(calib["notes"])

    if calibrated:
        min_wall, gap_range, snap = _MIN_WALL_MM, _GAP_RANGE_MM, _SNAP_MM
    else:
        min_wall, gap_range, snap = _MIN_WALL_UNCAL, _GAP_RANGE_UNCAL, _SNAP_UNCAL

    # ---------- 单位换算（y 轴翻转为向上，对齐 CAD 习惯） ----------
    segs = [(x1 * factor, y1 * factor, x2 * factor, y2 * factor) for x1, y1, x2, y2 in segs_pt]
    texts = [{
        "text": w["text"],
        "x": w["x"] * factor,
        "y": w["y"] * factor,
        "height": w["height"] * factor,
        "layer": "pdf_text",
    } for w in words_pt]

    # ---------- 线段分类：墙 / 门洞 / 窗 / 符号 ----------
    result = _classify_geometry(segs, calibrated, min_wall, gap_range, snap)
    walls = result["walls"]           # [(x1,y1,x2,y2,t)] 含洞口桥接段，已做 T 型分割
    base["doors"] = result["doors"]
    base["windows"] = result["windows"]
    base["pdf"]["unclassified_segment_count"] = result["unclassified_count"]
    base["limitations"].extend(result["notes"])

    base["walls"] = [(round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), t)
                     for x1, y1, x2, y2, t in walls]
    base["total_lines"] = len(base["walls"]) + len(base["doors"]) + len(base["windows"])
    base["wall_count"] = len(base["walls"])
    base["door_count"] = len(base["doors"])
    base["window_count"] = len(base["windows"])
    base["texts"] = texts

    all_pts = [(x1, y1) for x1, y1, _, _ in segs] + [(x2, y2) for x1, y1, x2, y2 in segs]
    if all_pts:
        base["bounds"] = (round(min(p[0] for p in all_pts), 1), round(min(p[1] for p in all_pts), 1),
                          round(max(p[0] for p in all_pts), 1), round(max(p[1] for p in all_pts), 1))

    # ---------- 房间闭环（cad_reader 有向半边面遍历，输入已桥接+T型分割） ----------
    rooms = detect_room_faces_from_walls(walls, texts, snap=snap)
    rooms, outline = _separate_outline(rooms)
    base["detected_rooms"] = rooms
    base["outline"] = outline

    # ---------- 置信度与限制 ----------
    base["confidence"] = _overall_confidence(calibrated, rooms, base["doors"], base["windows"])
    if not calibrated:
        base["limitations"].append(
            "比例尺未能校准：坐标单位仍是 point 而非毫米，房间面积/尺寸不可信，"
            "只输出几何拓扑。请显式传入 scale（如 scale='1:50'）或在图纸中保留尺寸标注。")
    if not rooms and calibrated:
        base["limitations"].append("已校准但未识别出房间闭环：墙线可能不闭合或图纸并非平面图。")
    if not base["doors"]:
        base["limitations"].append("未识别出门洞，动线/入口判断不可靠。")
    base["limitations"].append("矢量 PDF 不含图层语义，门窗按洞口宽度和符号启发式识别，需人工复核。")
    base["limitations"].append("PDF 图纸不能证明承重墙、管井、烟道和水电条件，仍需结构图或人工确认。")
    base["accepted"] = True
    return base


# ---------------------------------------------------------------- 矢量提取

def _extract_segments(page):
    """提取页面全部直线段（含细矩形的边），返回 pt 坐标、y 轴向上。"""
    h = float(page.height)
    segs = []
    for line in page.lines:
        segs.append((float(line["x0"]), h - float(line["bottom"]),
                     float(line["x1"]), h - float(line["top"])))
    for rect in page.rects:
        x0, x1 = float(rect["x0"]), float(rect["x1"])
        y0, y1 = h - float(rect["bottom"]), h - float(rect["top"])
        segs.extend([
            (x0, y0, x1, y0), (x1, y0, x1, y1),
            (x1, y1, x0, y1), (x0, y1, x0, y0),
        ])
    # 去重（矩形边与线可能重复）
    seen = set()
    unique = []
    for x1, y1, x2, y2 in segs:
        key = (round(min(x1, x2), 1), round(min(y1, y2), 1),
               round(max(x1, x2), 1), round(max(y1, y2), 1))
        if key in seen:
            continue
        seen.add(key)
        if math.hypot(x2 - x1, y2 - y1) > 0.5:
            unique.append((x1, y1, x2, y2))
    return unique


def _extract_words(page):
    """提取文字及位置（pt，y 轴向上，取词中心）。"""
    h = float(page.height)
    words = []
    for w in page.extract_words() or []:
        words.append({
            "text": w["text"],
            "x": (float(w["x0"]) + float(w["x1"])) / 2,
            "y": h - (float(w["top"]) + float(w["bottom"])) / 2,
            "height": float(w["bottom"]) - float(w["top"]),
        })
    return words


# ---------------------------------------------------------------- 比例尺校准

def _calibrate_scale(scale_param, raw_text, words_pt, segs_pt):
    """按优先级校准 pt→mm 比例。返回校准结果 dict。"""
    notes = []

    # 1) 显式参数（人工事实优先于一切推断）
    if scale_param:
        explicit = _parse_scale_param(scale_param, segs_pt)
        if explicit:
            factor, source, conf, note = explicit
            if note:
                notes.append(note)
            return {"pt_to_mm": factor, "scale_source": source, "scale_confidence": conf,
                    "dimensions_calibrated": True, "scale_votes": 0, "notes": notes}
        notes.append(f"显式比例参数 '{scale_param}' 无法解析，已忽略，继续自动校准。")

    # 2) 图纸比例文字（"比例 1:50"）
    text_factor = None
    match = _SCALE_TEXT_RE.search(raw_text or "")
    if match:
        denom = int(match.group(1))
        if 1 <= denom <= 1000:
            text_factor = MM_PER_PT * denom

    # 3) 尺寸标注数字反推（聚类投票）
    dim_factor, dim_votes = _infer_scale_from_dimensions(words_pt, segs_pt)

    if text_factor and dim_factor:
        if abs(text_factor - dim_factor) / text_factor <= 0.05:
            return {"pt_to_mm": text_factor, "scale_source": "scale_text+dimension_text",
                    "scale_confidence": 0.9, "dimensions_calibrated": True,
                    "scale_votes": dim_votes, "notes": notes}
        notes.append(
            f"图纸比例文字(1:{round(text_factor / MM_PER_PT)})与尺寸标注反推比例不一致，"
            "采用尺寸标注投票结果，比例需人工复核。")
        return {"pt_to_mm": dim_factor, "scale_source": "dimension_text_conflict",
                "scale_confidence": 0.55, "dimensions_calibrated": True,
                "scale_votes": dim_votes, "notes": notes}
    if text_factor:
        return {"pt_to_mm": text_factor, "scale_source": "scale_text",
                "scale_confidence": 0.8, "dimensions_calibrated": True,
                "scale_votes": 0, "notes": notes}
    if dim_factor:
        conf = 0.85 if dim_votes >= 2 else 0.6
        return {"pt_to_mm": dim_factor, "scale_source": "dimension_text",
                "scale_confidence": conf, "dimensions_calibrated": True,
                "scale_votes": dim_votes, "notes": notes}

    # 4) 失败：保持 pt 坐标，如实标注
    return {"pt_to_mm": 1.0, "scale_source": "uncalibrated", "scale_confidence": 0.2,
            "dimensions_calibrated": False, "scale_votes": 0, "notes": notes}


def _parse_scale_param(scale_param, segs_pt):
    """解析 '1:50' 或图幅（'A3' 等）。返回 (factor, source, confidence, note)。"""
    text = str(scale_param).strip()
    match = _SCALE_TEXT_RE.search(text)
    if match:
        denom = int(match.group(1))
        if 1 <= denom <= 1000:
            return MM_PER_PT * denom, "explicit_param", 0.95, None
        return None
    upper = text.upper()
    if upper in _PAPER_SIZES_MM and segs_pt:
        xs = [x for x1, _, x2, _ in segs_pt for x in (x1, x2)]
        span_pt = max(xs) - min(xs)
        if span_pt > 0:
            # 图幅反推假设图形横向铺满整张纸，误差较大，置信度低
            return (_PAPER_SIZES_MM[upper] / span_pt, "explicit_paper_size", 0.5,
                    f"按图幅 {upper} 反推比例（假设图形横向铺满图幅），精度有限，建议改用 '1:N' 参数。")
    return None


def _infer_scale_from_dimensions(words_pt, segs_pt):
    """从尺寸标注数字反推比例：数字文本 ↔ 最近长线段，比例聚类投票。"""
    long_segs = [s for s in segs_pt if math.hypot(s[2] - s[0], s[3] - s[1]) >= 25]
    if not long_segs:
        return None, 0

    ratios = []
    for w in words_pt:
        value_mm = _parse_dimension_value(w["text"])
        if not value_mm:
            continue
        best = None
        best_dist = 80.0  # 标注文字应贴近被标注线段
        for seg in long_segs:
            dist = _point_seg_distance(w["x"], w["y"], seg)
            if dist < best_dist:
                best_dist = dist
                best = seg
        if not best:
            continue
        seg_len = math.hypot(best[2] - best[0], best[3] - best[1])
        ratio = value_mm / seg_len
        if 2.0 <= ratio <= 300.0:  # 约 1:5 ~ 1:1000 图纸
            ratios.append(ratio)

    if not ratios:
        return None, 0

    ratios.sort()
    clusters = []
    for r in ratios:
        if clusters and abs(r - clusters[-1][-1]) / clusters[-1][-1] <= 0.04:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    best = max(clusters, key=len)
    median = best[len(best) // 2]
    return median, len(best)


def _parse_dimension_value(text):
    """解析尺寸标注数字：'4200'→4200mm；'3.600'→3600mm。"""
    text = (text or "").strip().replace(",", "")
    if _NUM_MM_RE.match(text):
        value = int(text)
        return float(value) if value >= 100 else None
    match = _NUM_M_RE.match(text)
    if match:
        return float(text) * 1000.0
    return None


def _point_seg_distance(px, py, seg):
    x1, y1, x2, y2 = seg
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (length * length)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


# ---------------------------------------------------------------- 几何分类

def _classify_geometry(segs, calibrated, min_wall, gap_range, snap):
    """墙线 / 门洞缺口 / 窗符号识别。坐标单位：已校准为 mm 或未校准 pt。"""
    notes = []
    axis_segs = []      # ("H"|"V", line_coord, p_start, p_end, x1,y1,x2,y2)
    diagonal_segs = []
    angle_tol = max(snap * 0.4, 1.0)
    for x1, y1, x2, y2 in segs:
        if abs(y2 - y1) <= angle_tol:
            y = (y1 + y2) / 2
            a, b = sorted([x1, x2])
            axis_segs.append(["H", y, a, b, x1, y1, x2, y2, False])
        elif abs(x2 - x1) <= angle_tol:
            x = (x1 + x2) / 2
            a, b = sorted([y1, y2])
            axis_segs.append(["V", x, a, b, x1, y1, x2, y2, False])
        else:
            diagonal_segs.append((x1, y1, x2, y2))

    # 全局外轮廓（判断内/外墙洞口）
    if axis_segs:
        xs = [s[2] for s in axis_segs] + [s[3] for s in axis_segs] + [s[1] for s in axis_segs]
        all_x = [s[4] for s in axis_segs] + [s[6] for s in axis_segs]
        all_y = [s[5] for s in axis_segs] + [s[7] for s in axis_segs]
        bbox = (min(all_x), min(all_y), max(all_x), max(all_y))
    else:
        bbox = (0, 0, 0, 0)
    edge_tol = 300.0 if calibrated else 20.0

    # 共线分组 → 找洞口间隙
    clusters = _cluster_collinear(axis_segs, snap)
    openings = []
    for cluster in clusters:
        direction = cluster[0][0]
        line_coord = sum(s[1] for s in cluster) / len(cluster)
        runs = _merge_runs(sorted((s[2], s[3]) for s in cluster), snap)
        for (a1, b1), (a2, b2) in zip(runs, runs[1:]):
            gap = a2 - b1
            if gap_range[0] <= gap <= gap_range[1]:
                openings.append({
                    "axis": direction,
                    "line": line_coord,
                    "gap_start": b1,
                    "gap_end": a2,
                    "width": gap,
                })

    doors = []
    windows = []
    consumed_diagonals = set()
    for opening in openings:
        gap_mid = (opening["gap_start"] + opening["gap_end"]) / 2
        if opening["axis"] == "H":
            p1 = (opening["gap_start"], opening["line"])
            p2 = (opening["gap_end"], opening["line"])
            exterior = min(abs(opening["line"] - bbox[1]), abs(opening["line"] - bbox[3])) <= edge_tol
        else:
            p1 = (opening["line"], opening["gap_start"])
            p2 = (opening["line"], opening["gap_end"])
            exterior = min(abs(opening["line"] - bbox[0]), abs(opening["line"] - bbox[2])) <= edge_tol

        # 门扇斜线：端点贴近洞口端点的斜线，归为门扇（不进墙线）
        has_leaf = False
        for idx, d in enumerate(diagonal_segs):
            if idx in consumed_diagonals:
                continue
            for (dx1, dy1) in ((d[0], d[1]), (d[2], d[3])):
                if min(math.hypot(dx1 - p1[0], dy1 - p1[1]),
                       math.hypot(dx1 - p2[0], dy1 - p2[1])) <= max(opening["width"], snap * 2):
                    consumed_diagonals.add(idx)
                    has_leaf = True
                    break

        # 窗符号：与墙平行、垂直偏移在墙厚范围内、覆盖洞口的线段
        symbol_segs = []
        for s in axis_segs:
            if s[8] or s[0] != opening["axis"]:
                continue
            offset = abs(s[1] - opening["line"])
            max_offset = 400.0 if calibrated else 25.0
            if offset <= snap or offset > max_offset:
                continue
            overlap = min(s[3], opening["gap_end"]) - max(s[2], opening["gap_start"])
            if overlap >= 0.6 * opening["width"]:
                symbol_segs.append(s)

        if not exterior:
            doors.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
        elif symbol_segs:
            for s in symbol_segs:
                s[8] = True  # 标记为窗符号，不再作为墙线
            windows.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
        else:
            doors.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
            notes.append("外墙存在无窗符号的洞口，按门洞处理（可能是入户门/阳台门），需人工确认。")

    # 墙线 = 未被消费的横竖长线段 + 洞口桥接段（供闭环检测把房间封合）
    walls = []
    for s in axis_segs:
        if s[8]:
            continue
        if s[3] - s[2] >= min_wall:
            walls.append((s[4], s[5], s[6], s[7], 120))
    for opening in openings:
        if opening["axis"] == "H":
            walls.append((opening["gap_start"], opening["line"], opening["gap_end"], opening["line"], 120))
        else:
            walls.append((opening["line"], opening["gap_start"], opening["line"], opening["gap_end"], 120))

    walls = _split_at_t_junctions(walls, snap)

    unclassified = len(diagonal_segs) - len(consumed_diagonals)
    if unclassified > 0:
        notes.append(f"{unclassified} 条斜线/符号线段无法归类，已忽略。")

    return {
        "walls": walls,
        "doors": doors,
        "windows": windows,
        "unclassified_count": max(0, unclassified),
        "notes": notes,
    }


def _cluster_collinear(axis_segs, snap):
    """把同方向、线坐标接近的线段聚成共线组。"""
    clusters = []
    for seg in sorted(axis_segs, key=lambda s: (s[0], s[1])):
        placed = False
        for cluster in clusters:
            if cluster[0][0] == seg[0] and abs(seg[1] - cluster[0][1]) <= snap:
                cluster.append(seg)
                placed = True
                break
        if not placed:
            clusters.append([seg])
    return clusters


def _merge_runs(intervals, snap):
    """合并重叠/相邻（间隙小于 snap）的区间。"""
    runs = []
    for a, b in intervals:
        if runs and a - runs[-1][1] < snap:
            runs[-1][1] = max(runs[-1][1], b)
        else:
            runs.append([a, b])
    return [(a, b) for a, b in runs]


def _split_at_t_junctions(walls, snap):
    """在 T 型交叉处断开墙段：一段的端点落在另一段内部时，后者在交点断开。

    PDF 图纸没有图层语义，内部隔墙常与外墙/其他墙形成 T 型交叉；
    不断开的话闭环检测的邻接图缺少交点节点，内部房间环无法闭合。
    """
    walls = [list(w) for w in walls]
    for _ in range(12):
        changed = False
        out = []
        for i, w in enumerate(walls):
            x1, y1, x2, y2, t = w
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            cuts = []
            for j, o in enumerate(walls):
                if i == j:
                    continue
                for px, py in ((o[0], o[1]), (o[2], o[3])):
                    proj = ((px - x1) * dx + (py - y1) * dy) / length
                    if proj < snap or proj > length - snap:
                        continue
                    perp = abs((px - x1) * dy - (py - y1) * dx) / length
                    if perp < snap:
                        cuts.append(proj)
            if not cuts:
                out.append(w)
                continue
            cuts.sort()
            merged_cuts = []
            for c in cuts:
                if not merged_cuts or c - merged_cuts[-1] > snap:
                    merged_cuts.append(c)
            ux, uy = dx / length, dy / length
            points = [(x1, y1)] + [(x1 + ux * c, y1 + uy * c) for c in merged_cuts] + [(x2, y2)]
            for a, b in zip(points, points[1:]):
                out.append([a[0], a[1], b[0], b[1], t])
            changed = True
        walls = out
        if not changed:
            break
    return [tuple(w) for w in walls]


def _separate_outline(rooms):
    """把包含其他房间质心的最大环判为户型外轮廓，不当作房间。"""
    if len(rooms) < 2:
        return rooms, None
    centroids = []
    for room in rooms:
        pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        if not pts:
            centroids.append(None)
            continue
        centroids.append((sum(p[0] for p in pts) / len(pts),
                          sum(p[1] for p in pts) / len(pts)))
    for i, room in enumerate(rooms):
        poly = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        if len(poly) < 3:
            continue
        contained = sum(
            1 for j, c in enumerate(centroids)
            if j != i and c and _point_in_polygon(c[0], c[1], poly)
        )
        if contained >= 2:
            outline = dict(room)
            outline["note"] = "户型外轮廓（包含全部房间），不计入房间清单"
            rest = [r for k, r in enumerate(rooms) if k != i]
            return rest, outline
    return rooms, None


def _point_in_polygon(px, py, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < x_cross:
                inside = not inside
    return inside


def _overall_confidence(calibrated, rooms, doors, windows):
    if not calibrated:
        return 0.25
    if not rooms:
        return 0.5
    conf = 0.66
    if doors:
        conf = 0.7
    if doors and windows:
        conf = 0.72
    return conf
