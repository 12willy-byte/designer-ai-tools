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
            f"图纸包含 {base['pdf']['curve_count']} 条曲线路径：其中直线折线已切段提取，"
            "圆弧部分（门弧等）不参与几何解析。")

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

    # ---------- 线段分类 + 房间闭环（两遍法） ----------
    # 第一遍用全部线段；若识别出户型外轮廓，把外轮廓之外的标注线/延长线裁掉
    # 再跑第二遍——真实图纸的标注线常在墙外 1.5m 以上，会制造假洞口、
    # 假闭环和虚大的 bounds。
    def _analyze(segs_mm):
        result = _classify_geometry(segs_mm, calibrated, min_wall, gap_range, snap)
        wall_list = result["walls"]
        room_list = detect_room_faces_from_walls(wall_list, texts, snap=snap)
        room_list, outline_face = _separate_outline(room_list)
        return result, wall_list, room_list, outline_face

    result, walls, rooms, outline = _analyze(segs)
    if outline and outline.get("floor_points"):
        margin = 1000.0 if calibrated else 120.0
        xs = [p["x"] for p in outline["floor_points"]]
        ys = [p["y"] for p in outline["floor_points"]]
        x0, x1 = min(xs) - margin, max(xs) + margin
        y0, y1 = min(ys) - margin, max(ys) + margin
        clipped = [s for s in segs
                   if x0 <= (s[0] + s[2]) / 2 <= x1 and y0 <= (s[1] + s[3]) / 2 <= y1]
        if len(clipped) < len(segs):
            base["limitations"].append(
                f"已按户型外轮廓外扩 {round(margin)}mm 裁剪图面：剔除外侧标注线/延长线 "
                f"{len(segs) - len(clipped)} 条后重新解析。")
            result, walls, rooms, outline = _analyze(clipped)
            segs = clipped

    base["doors"] = result["doors"]
    base["windows"] = result["windows"]
    base["pdf"]["unclassified_segment_count"] = result["unclassified_count"]
    base["limitations"].extend(result["notes"])

    # 缝隙假房间过滤：双线墙未配对残余、符号描边会闭合成细条小环，
    # 按最短边/面积下限剔除；标注线与墙围成的环会被标注数字命名，
    # 纯数字命名的"房间"一并剔除（仅在校准后按 mm 判断）。
    if calibrated:
        kept = []
        dropped_slits = 0
        dropped_numeric = 0
        for room in rooms:
            name = (room.get("name") or "").strip()
            if re.fullmatch(r"\d{3,5}", name):
                dropped_numeric += 1
                continue
            pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
            if pts:
                w = max(p[0] for p in pts) - min(p[0] for p in pts)
                d = max(p[1] for p in pts) - min(p[1] for p in pts)
                if min(w, d) < 450.0 or room.get("area_m2", 0) < 1.0:
                    dropped_slits += 1
                    continue
            kept.append(room)
        if dropped_slits:
            base["limitations"].append(
                f"{dropped_slits} 个细条/微小闭环（墙缝或符号描边，最短边 <450mm 或面积 <1㎡）"
                "已从房间清单剔除。")
        if dropped_numeric:
            base["limitations"].append(
                f"{dropped_numeric} 个由尺寸标注线与墙体围成的闭环（以标注数字命名）"
                "已从房间清单剔除。")
        rooms = kept

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
    """提取页面全部直线段（含细矩形的边），返回 pt 坐标、y 轴向上。

    两个真实图纸的坑在此处理：
    1. 图框线（贴页面边缘、几乎贯通整幅的长线）剔除：它们不是墙体，
       会把 bounds/外轮廓撑到整页，并制造贯穿全图的假洞口。
    2. CAD 导出的折线（polyline）会被 pdfplumber 归为 curves——其中大量
       是全程笔直的墙线路径。按方向突变把折线切成直线段提取；
       真正带弧的（门弧）只取其中的直线部分（门扇线），弧线本身忽略。
    """
    h = float(page.height)
    w_page = float(page.width)
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
    for curve in page.curves:
        segs.extend(_straight_runs_from_curve(curve, h))
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
    edge_tol = max(3.0, 0.015 * max(w_page, h))
    filtered = []
    for x1, y1, x2, y2 in unique:
        length = math.hypot(x2 - x1, y2 - y1)
        if abs(y2 - y1) <= edge_tol and length > 0.55 * w_page:
            y = (y1 + y2) / 2
            if y <= edge_tol or y >= h - edge_tol:
                continue  # 上/下图框边
        if abs(x2 - x1) <= edge_tol and length > 0.55 * h:
            x = (x1 + x2) / 2
            if x <= edge_tol or x >= w_page - edge_tol:
                continue  # 左/右图框边
        filtered.append((x1, y1, x2, y2))
    return filtered


def _straight_runs_from_curve(curve, page_height):
    """把 curve 路径按方向突变切成直线段（y 轴翻转为向上）。

    门弧一类路径 = 直线门扇 + 贝塞尔弧：弧段控制点会产生持续的方向
    变化，被切碎后按最小长度过滤；笔直折线则整段保留。
    """
    pts = curve.get("pts") or []
    if len(pts) < 2:
        return []
    runs = []
    run_start = None
    prev_dir = None
    for i in range(len(pts) - 1):
        x1, y1 = float(pts[i][0]), page_height - float(pts[i][1])
        x2, y2 = float(pts[i + 1][0]), page_height - float(pts[i + 1][1])
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if seg_len < 0.3:
            continue
        direction = math.atan2(y2 - y1, x2 - x1)
        if prev_dir is not None:
            delta = abs((direction - prev_dir + math.pi) % (2 * math.pi) - math.pi)
            if delta > 0.06:  # 方向突变：结束上一段直线
                if run_start is not None:
                    runs.append((run_start[0], run_start[1], x1, y1))
                run_start = (x1, y1)
        if run_start is None:
            run_start = (x1, y1)
        prev_dir = direction
    if run_start is not None:
        runs.append((run_start[0], run_start[1], x2, y2))
    return [r for r in runs if math.hypot(r[2] - r[0], r[3] - r[1]) >= 2.0]


def _extract_words(page):
    """提取文字及位置（pt，y 轴向上，取词中心）。upright=False 表示竖排/旋转文字。"""
    h = float(page.height)
    words = []
    for w in page.extract_words() or []:
        words.append({
            "text": w["text"],
            "x": (float(w["x0"]) + float(w["x1"])) / 2,
            "y": h - (float(w["top"]) + float(w["bottom"])) / 2,
            "height": float(w["bottom"]) - float(w["top"]),
            "upright": bool(w.get("upright", True)),
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
    """从尺寸标注数字反推比例：数字文本 ↔ 最近长线段，比例聚类投票。

    真实图纸的两个怪癖在这里处理：
    1. 竖排标注常被反向读取（"1380" 读成 "0831"、"11072" 读成 "27011"），
       每个数字同时尝试正读/反读两个候选值，靠聚类投票让正确读法胜出；
    2. 标注文字优先匹配同方向的线段（横排数字 ↔ 水平标注线，
       竖排数字 ↔ 竖直标注线），减少贴到附近墙线上的错配。
    """
    long_segs = [s for s in segs_pt if math.hypot(s[2] - s[0], s[3] - s[1]) >= 25]
    if not long_segs:
        return None, 0
    # 严格横平竖直：CAD 常在标注文字处画斜向短符号线（45° 斜杠/遮罩），
    # 它们穿过文字、距离≈0，会抢走匹配——标注对应的永远是长直线。
    horiz = [s for s in long_segs if abs(s[3] - s[1]) <= 2.0]
    vert = [s for s in long_segs if abs(s[2] - s[0]) <= 2.0]

    ratios = []
    for w in words_pt:
        values = []
        for candidate in (w["text"], (w["text"] or "")[::-1]):
            value_mm = _parse_dimension_value(candidate)
            if value_mm and value_mm not in values:
                values.append(value_mm)
        if not values:
            continue
        pool = (horiz if w.get("upright", True) else vert) or long_segs
        candidates = []
        for seg in pool:
            dist = _point_seg_distance(w["x"], w["y"], seg)
            if dist < 3.0 or dist > 80.0:
                continue  # 穿过文字本身的是符号线/遮罩；太远的不相关
            candidates.append((dist, seg))
        if not candidates:
            continue
        # 标注对应的永远是长直线：在最近距离 +10pt 窗口内取最长线段
        # （文字遮罩框/引出线比标注线更贴近文字，但短得多）。
        d_min = min(d for d, _ in candidates)
        best = max((seg for d, seg in candidates if d <= d_min + 10.0),
                   key=lambda s: math.hypot(s[2] - s[0], s[3] - s[1]))
        seg_len = math.hypot(best[2] - best[0], best[3] - best[1])
        for value_mm in values:
            ratio = value_mm / seg_len
            if 2.0 <= ratio <= 300.0:  # 约 1:5 ~ 1:1000 图纸
                ratios.append((ratio, seg_len))

    if not ratios:
        return None, 0

    ratios.sort(key=lambda item: item[0])
    clusters = []
    for r, weight in ratios:
        if clusters and abs(r - clusters[-1][-1][0]) / clusters[-1][-1][0] <= 0.04:
            clusters[-1].append((r, weight))
        else:
            clusters.append([(r, weight)])
    best = max(clusters, key=len)
    # 加权中位数：被标注线段越长（总开间/总进深一类），比例越可信。
    # 真实图纸的分段标注常与总尺寸有出入（文字被改、链长不含墙厚），
    # 简单中位数会被大量短分段标注带偏。
    total_weight = sum(w for _, w in best)
    acc = 0.0
    median = best[-1][0]
    for r, weight in best:
        acc += weight
        if acc >= total_weight / 2:
            median = r
            break
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
    """墙线 / 门洞缺口 / 窗符号识别。坐标单位：已校准为 mm 或未校准 pt。

    双线墙处理：真实 CAD 图纸的墙大多画成一对平行线（墙厚 100~300mm）。
    先把"间距在墙厚范围内、投影高度重叠"的平行线对合并成墙中线，
    洞口检测与墙线输出都以中线为准——否则两条墙面线各自成簇，
    墙缝会被闭合成狭长假房间，门洞也会被重复计数。
    合并不足 3 对时判定为单线图纸，回退到旧的单线逻辑。
    """
    notes = []
    axis_segs = []      # ("H"|"V", line_coord, p_start, p_end, x1,y1,x2,y2, consumed)
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

    # ---------- 双线墙合并 ----------
    if calibrated:
        pair_range, min_pair_len = (60.0, 350.0), 150.0     # 墙厚 60~350mm
    else:
        pair_range, min_pair_len = (8.0, 45.0), 12.0        # 未校准按 pt 经验值
    # 先把平行近距线（同一堵墙的两条面线）的端点投影为彼此断点：
    # 真实图纸常一面线整通、另一面线被隔断，断点不对齐就无法共 extent 配对。
    axis_segs = _align_breakpoints(axis_segs, pair_range[1], snap)
    centerlines, merged_idx = _merge_wall_pairs(axis_segs, pair_range, min_pair_len)
    double_line_mode = len(centerlines) >= 3
    if double_line_mode:
        notes.append(
            f"识别到双线墙表达：{len(centerlines)} 段墙由平行双线合并为墙中线，"
            "墙缝不再参与房间闭环。")

    # 洞口检测的基底：双线模式用「墙中线 + 长单线」——中线保证门洞不被
    # 双面线重复计数，长单线覆盖单线绘制的外墙/栏板（真实图纸常混用）。
    if double_line_mode:
        gap_source = list(centerlines)
        for i, s in enumerate(axis_segs):
            if s[8] or i in merged_idx:
                continue
            if s[3] - s[2] >= min_wall:
                gap_source.append(s)
    else:
        gap_source = axis_segs

    # 全局外轮廓（判断内/外墙洞口）；双线模式用中线包围盒，避开标注线干扰
    bbox_source = gap_source if gap_source else axis_segs
    if bbox_source:
        all_x = [s[4] for s in bbox_source] + [s[6] for s in bbox_source]
        all_y = [s[5] for s in bbox_source] + [s[7] for s in bbox_source]
        bbox = (min(all_x), min(all_y), max(all_x), max(all_y))
    else:
        bbox = (0, 0, 0, 0)
    edge_tol = 300.0 if calibrated else 20.0

    # 共线分组 → 找洞口间隙。纯单线簇（无墙中线）的洞口可能是家具缺口，
    # 必须有门扇斜线或窗符号佐证才采信；含墙中线的簇直接采信。
    centerline_ids = {id(c) for c in centerlines}
    clusters = _cluster_collinear(gap_source, snap)
    openings = []
    for cluster in clusters:
        direction = cluster[0][0]
        line_coord = sum(s[1] for s in cluster) / len(cluster)
        has_center = any(id(s) in centerline_ids for s in cluster)
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
                    "needs_proof": not has_center,
                })

    doors = []
    windows = []
    consumed_diagonals = set()
    for opening in openings:
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

        if opening.get("needs_proof") and not (symbol_segs or has_leaf):
            opening["rejected"] = True
            continue  # 纯单线簇的无佐证洞口：家具缺口/符号间隙，不桥接、不计数

        if not exterior:
            doors.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
        elif symbol_segs:
            for s in symbol_segs:
                s[8] = True  # 标记为窗符号，不再作为墙线
            windows.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
        else:
            doors.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
            notes.append("外墙存在无窗符号的洞口，按门洞处理（可能是入户门/阳台门），需人工确认。")

    # 墙线输出 + 洞口桥接段（供闭环检测把房间封合）
    walls = []
    if double_line_mode:
        # 双线模式：墙 = 合并出的中线 + 未配对的长单线（单线外墙/栏板/标注线都会
        # 进来——标注线造成的数值命名假房间和细条环在闭环后统一过滤；
        # 中线短门槛段也保留，否则相邻门洞间的墙垛会漏）。
        min_center = 100.0 if calibrated else 8.0
        for c in centerlines:
            if c[3] - c[2] >= min_center:
                walls.append((c[4], c[5], c[6], c[7], 120))
        singles = 0
        for i, s in enumerate(axis_segs):
            if s[8] or i in merged_idx:
                continue
            if s[3] - s[2] >= min_wall:
                walls.append((s[4], s[5], s[6], s[7], 120))
                singles += 1
        if singles:
            notes.append(
                f"双线墙模式：另计入 {singles} 条未配对长单线（单线墙体/标注线/家具轮廓），"
                "由此产生的假房间已在闭环后按形态与命名过滤，仍需人工复核。")
    else:
        for s in axis_segs:
            if s[8]:
                continue
            if s[3] - s[2] >= min_wall:
                walls.append((s[4], s[5], s[6], s[7], 120))
    for opening in openings:
        if opening.get("rejected"):
            continue
        if opening["axis"] == "H":
            walls.append((opening["gap_start"], opening["line"], opening["gap_end"], opening["line"], 120))
        else:
            walls.append((opening["line"], opening["gap_start"], opening["line"], opening["gap_end"], 120))

    # 几何清理（真实 CAD 图纸必需）：
    # 1) 小于门洞下限的共线缝隙是绘图断口，桥接为墙；
    # 2) 墙中线在转角/T 型处普遍差半个墙厚够不到彼此，把够不到的端点
    #    延长到与另一堵墙相交（延长量以最大墙厚为限，小于门洞下限，
    #    不会误跨门洞）。不做这两步，闭环检测的邻接图没有任何交点节点。
    max_ext = 350.0 if calibrated else 45.0
    walls = _bridge_small_gaps(walls, snap, gap_range[0])
    walls = _extend_to_intersections(walls, snap, max_ext)
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


def _align_breakpoints(axis_segs, offset_max, snap):
    """把平行近距线对的端点投影为彼此断点。

    真实图纸里同一堵墙的两条面线断点常常不对齐（外侧面线一笔画通，
    内侧面线被房间隔断），不先对齐断点，"投影基本重合"的配对条件
    会把整通面线和它的一小段配偶判为不匹配，导致整段外墙丢失。
    """
    n = len(axis_segs)
    order = sorted(range(n), key=lambda i: (axis_segs[i][0], axis_segs[i][1]))
    cuts = [[] for _ in range(n)]
    for pos, i in enumerate(order):
        a = axis_segs[i]
        for j in order[pos + 1:]:
            b = axis_segs[j]
            if b[0] != a[0] or b[1] - a[1] > offset_max:
                break
            if b[1] - a[1] <= snap:
                continue  # 近似共线的由共线分组/snap 处理
            for p in (a[2], a[3]):
                if b[2] + snap < p < b[3] - snap:
                    cuts[j].append(p)
            for p in (b[2], b[3]):
                if a[2] + snap < p < a[3] - snap:
                    cuts[i].append(p)
    out = []
    for i, s in enumerate(axis_segs):
        if not cuts[i]:
            out.append(s)
            continue
        points = [s[2]] + sorted(set(cuts[i])) + [s[3]]
        for u, v in zip(points, points[1:]):
            if v - u < 1.0:
                continue
            if s[0] == "H":
                out.append(["H", s[1], u, v, u, s[1], v, s[1], False])
            else:
                out.append(["V", s[1], u, v, s[1], u, s[1], v, False])
    return out


def _merge_wall_pairs(axis_segs, offset_range, min_pair_len):
    """把"平行、间距在墙厚范围、投影基本重合"的线对合并为墙中线。

    返回 (centerlines, merged_idx)。centerlines 与 axis_segs 同构（9 元素）。
    配对排序以投影重合度优先（重合度相同再取间距小者）：墙的两条面线
    断点对齐后重合度接近 1，而墙缝里的窗线/符号线只覆盖洞口一段，
    重合度低——避免面线被更近的窗线"抢走"导致整堵墙合并不出来。
    """
    n = len(axis_segs)
    order = sorted(range(n), key=lambda i: (axis_segs[i][0], axis_segs[i][1]))
    pairs = []
    for pos, i in enumerate(order):
        a = axis_segs[i]
        for j in order[pos + 1:]:
            b = axis_segs[j]
            if b[0] != a[0] or b[1] - a[1] > offset_range[1]:
                break
            d = b[1] - a[1]
            if d < offset_range[0]:
                continue
            la, lb = a[3] - a[2], b[3] - b[2]
            if la < min_pair_len or lb < min_pair_len:
                continue
            overlap = min(a[3], b[3]) - max(a[2], b[2])
            overlap_ratio = overlap / max(la, lb)
            if overlap_ratio < 0.6:
                continue
            pairs.append((-overlap_ratio, d, i, j))
    pairs.sort()
    used = set()
    centerlines = []
    for _neg_ratio, d, i, j in pairs:
        if i in used or j in used:
            continue
        used.add(i)
        used.add(j)
        a, b = axis_segs[i], axis_segs[j]
        line = (a[1] + b[1]) / 2
        lo, hi = min(a[2], b[2]), max(a[3], b[3])
        if a[0] == "H":
            centerlines.append(["H", line, lo, hi, lo, line, hi, line, False])
        else:
            centerlines.append(["V", line, lo, hi, line, lo, line, hi, False])
    return centerlines, used


def _bridge_small_gaps(walls, snap, min_opening):
    """桥接共线墙段之间小于门洞下限的缝隙（绘图断口，不是洞口）。"""
    axis = []
    for w in walls:
        x1, y1, x2, y2, t = w
        if abs(y2 - y1) <= snap * 0.4:
            y = (y1 + y2) / 2
            a, b = sorted([x1, x2])
            axis.append(["H", y, a, b])
        elif abs(x2 - x1) <= snap * 0.4:
            x = (x1 + x2) / 2
            a, b = sorted([y1, y2])
            axis.append(["V", x, a, b])
    bridges = []
    for cluster in _cluster_collinear(axis, snap):
        direction = cluster[0][0]
        line_coord = sum(s[1] for s in cluster) / len(cluster)
        runs = _merge_runs(sorted((s[2], s[3]) for s in cluster), snap)
        for (a1, b1), (a2, b2) in zip(runs, runs[1:]):
            gap = a2 - b1
            if snap <= gap < min_opening:
                if direction == "H":
                    bridges.append((b1, line_coord, a2, line_coord, 120))
                else:
                    bridges.append((line_coord, b1, line_coord, a2, 120))
    return list(walls) + bridges


def _extend_to_intersections(walls, snap, max_ext):
    """把差一截够不到另一堵墙的端点延长到相交（最大延长 max_ext）。

    墙由平行双线合并成中线后，转角处两条中线各差约半个墙厚；
    不延长则邻接图没有交点节点，任何房间环都无法闭合。
    """
    hs = []   # [y, x_lo, x_hi]
    vs = []   # [x, y_lo, y_hi]
    for w in walls:
        x1, y1, x2, y2, _t = w
        if abs(y2 - y1) <= snap * 0.4:
            y = (y1 + y2) / 2
            a, b = sorted([x1, x2])
            hs.append([y, a, b])
        elif abs(x2 - x1) <= snap * 0.4:
            x = (x1 + x2) / 2
            a, b = sorted([y1, y2])
            vs.append([x, a, b])
    for h in hs:
        for v in vs:
            # 交点 (v[0], h[0])：只在"两线互相差一点就够到"时双向延长
            if h[1] - max_ext <= v[0] <= h[2] + max_ext and \
               v[1] - max_ext <= h[0] <= v[2] + max_ext:
                if v[0] < h[1] - snap:
                    h[1] = v[0]
                elif v[0] > h[2] + snap:
                    h[2] = v[0]
                if h[0] < v[1] - snap:
                    v[1] = h[0]
                elif h[0] > v[2] + snap:
                    v[2] = h[0]
    out = [(h[1], h[0], h[2], h[0], 120) for h in hs]
    out += [(v[0], v[1], v[0], v[2], 120) for v in vs]
    return out


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
