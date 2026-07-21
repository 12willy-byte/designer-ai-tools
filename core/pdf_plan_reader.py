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
_GAP_RANGE_MM = (500.0, 2600.0)       # 门洞级洞口宽度合理区间
_BALCONY_GAP_MM = (2600.0, 4000.0)    # 阳台/落地窗级大洞口：桥接但标记为虚拟墙
_OVERSIZED_GAP_MM = 8000.0            # 超过 4000mm 的开口不桥接，只记录 limitation
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
        "door_arcs": [],
        "door_details": [],
        "removed_doors": [],
        "removed_rooms": [],
        "furniture_lines": {"count": 0, "segments": [],
                            "note": "未与墙体网络连接的未配对单线（家具/标注轮廓）。"},
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
            "圆弧部分不参与墙体几何解析（门扇弧线另走内容流提取，作为门洞佐证）。")

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

    # ---------- 门扇弧线提取（内容流级，回收 pdfminer 丢失的符号实例） ----------
    door_arcs = []
    try:
        from core.pdf_symbol_extract import extract_door_arcs
        for arc in extract_door_arcs(pdf_path, page_number):
            door_arcs.append({
                "hinge": (round(arc["hinge"][0] * factor, 1),
                          round(arc["hinge"][1] * factor, 1)),
                "radius_mm": round(arc["radius_pt"] * factor, 1),
                "leaf_tip": (round(arc["leaf_tip"][0] * factor, 1),
                             round(arc["leaf_tip"][1] * factor, 1)),
                "closed": (round(arc["closed"][0] * factor, 1),
                           round(arc["closed"][1] * factor, 1)),
                "sweep_deg": arc["sweep_deg"],
            })
    except Exception as exc:  # 弧线只是增强证据，失败不阻断几何解析
        base["limitations"].append("门扇弧线提取失败（%s）：按无弧线证据处理。" % exc)
    if door_arcs:
        base["limitations"].append(
            f"从内容流识别到 {len(door_arcs)} 条门扇摆动弧线（铰链+半径≈门宽），"
            "作为门洞语义佐证。")
    base["door_arcs"] = door_arcs

    # ---------- 线段分类 + 房间闭环（两遍法） ----------
    # 第一遍用全部线段；若识别出户型外轮廓，把外轮廓之外的标注线/延长线裁掉
    # 再跑第二遍——真实图纸的标注线常在墙外 1.5m 以上，会制造假洞口、
    # 假闭环和虚大的 bounds。
    def _analyze(segs_mm):
        result = _classify_geometry(segs_mm, calibrated, min_wall, gap_range, snap)
        wall_list = result["walls"]
        # 面遍历前做图面清理：节点焊接（40~100mm 的错位节点/双线残余并点）、
        # 重边剔除、悬挂墙头剪枝。真实图纸的微几何噪声（窄缝、2-节点环、
        # 微三角、错位 T 节点）会让面遍历振荡或走进死胡同，产生不闭合/
        # 自交的退化"房间"。清理只用于闭环检测，对外墙线输出不变。
        face_walls = _weld_and_prune_for_faces(wall_list, snap)
        room_list = detect_room_faces_from_walls(face_walls, texts, snap=snap)
        room_list, invalid_count = _clean_and_validate_faces(room_list, face_walls, snap)
        if invalid_count:
            result["notes"].append(
                f"{invalid_count} 个退化闭环（边界不连贯或自交，多为墙缝/符号描边）"
                "已从房间清单剔除。")
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
    base["jamb_tick_gaps"] = result.get("tick_gaps") or []
    base["pdf"]["unclassified_segment_count"] = result["unclassified_count"]
    base["limitations"].extend(result["notes"])
    # 家具/标注浮动单线留痕：疑似家具/标注轮廓标记在此，供闭环过滤与复核。
    floating_singles = result.get("floating_singles") or []
    base["furniture_lines"] = {
        "count": len(floating_singles),
        "segments": [(round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1))
                     for x1, y1, x2, y2 in floating_singles],
        "note": "未接入墙体网络的未配对单线（疑似家具/陈设/标注轮廓）："
                "由它们封口的洞口需门扇/窗符号佐证，由它们主导的闭环已按"
                "家具线过滤剔除（见 removed_rooms），留痕供复核。",
    }

    # 假房间过滤（校准后按 mm 判断），逐级留痕：
    # 1) 纯数字命名的环：尺寸标注线与墙围成，剔除；
    # 2) 细条/微小环（最短边 <450mm 或面积 <1㎡）：墙缝/符号描边，剔除；
    # 3) 物理下限：净宽 <1m 的闭环不可能是房间（净宽 <1.5m 的窄带还需
    #    看边界构成，实测真假混叠，不做覆盖率剔除以免误杀真实走廊）；
    # 4) 家具描边：面积 <3㎡ 且边界 ≥50% 为未配对浮动单线（家具/标注）。
    # 判别信号是边界浮动单线占比——真实小房间的边界是墙中线/结构单线。
    # 剔除全部留痕 removed_rooms。
    if calibrated:
        single_segs = floating_singles  # 覆盖率只看疑似家具/标注的浮动单线
        kept = []
        removed_rooms = []
        dropped_slits = 0
        dropped_numeric = 0
        for room in rooms:
            name = (room.get("name") or "").strip()
            pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
            w = d = 0.0
            if pts:
                w = max(p[0] for p in pts) - min(p[0] for p in pts)
                d = max(p[1] for p in pts) - min(p[1] for p in pts)
            if re.fullmatch(r"\d{3,5}", name):
                dropped_numeric += 1
                removed_rooms.append({
                    "name": name, "area_m2": room.get("area_m2"),
                    "bbox_mm": [round(w), round(d)],
                    "reasons": ["以尺寸标注数字命名：标注线与墙体围成的闭环，不是房间"],
                })
                continue
            if pts:
                if min(w, d) < 450.0 or room.get("area_m2", 0) < 1.0:
                    dropped_slits += 1
                    removed_rooms.append({
                        "name": name or "未命名", "area_m2": room.get("area_m2"),
                        "bbox_mm": [round(w), round(d)],
                        "reasons": ["细条/微小闭环（最短边 <450mm 或面积 <1㎡），"
                                    "多为墙缝或符号描边"],
                    })
                    continue
                reasons = _furniture_room_reasons(room, w, d, single_segs, snap)
                if reasons:
                    removed_rooms.append({
                        "name": name or "未命名", "area_m2": room.get("area_m2"),
                        "bbox_mm": [round(w), round(d)],
                        "reasons": reasons,
                    })
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
        furniture_drops = [r for r in removed_rooms
                           if any("单线" in reason or "净宽" in reason
                                  for reason in r["reasons"])]
        if furniture_drops:
            base["limitations"].append(
                f"{len(furniture_drops)} 个闭环低于房间物理下限或边界主要由未配对单线"
                "（家具/标注轮廓）构成，已从房间清单剔除并留痕（removed_rooms）："
                + "、".join(f"{r['name']}（{r['area_m2']}㎡）" for r in furniture_drops)
                + "。")
        base["removed_rooms"] = removed_rooms
        rooms = kept

    # 开敞空间命名：按房间名文字的实际落点重命名；一个闭环内有多个房间名
    # （客餐厅一体等）标注为复合空间并给出逻辑分区，不伪造物理隔墙。
    composite_count = _relabel_rooms_by_inner_texts(rooms, texts)
    if composite_count:
        base["limitations"].append(
            f"{composite_count} 个开敞复合空间（一个闭环内含多个房间名，如客餐厅一体）："
            "按文字落点标注为复合空间并给出逻辑分区（zones），未伪造物理隔墙。")

    # 命名诚实化（PDF 路径）——命名环内优先：
    # 1) 落在闭环内部的房间名文字拥有该环的绝对命名权（见上面的
    #    _relabel_rooms_by_inner_texts）；环外文字只能兜底，且必须未被
    #    任何闭环占用——否则环外名字会被墙缝条带/家具碎片"偷名"
    #    （如"次卧"贴在 1m 宽条带上）；
    # 2) 环内无文字时用 2500mm 内最近的未占用文字兜底命名，标
    #    name_source=nearest_outside + 低置信；没有可用兜底文字或最近
    #    文字超过 2500mm 的闭环命名为"未命名空间"；
    # 3) 同名闭环按面积降序编号（卧室、卧室2……）：下游空间画像按名字
    #    合并同名房间，不编号会丢掉同名但独立的闭环（如两个卧室）；
    # 4) 超出 2500mm 的环进入文字-环亲和度评分路径（方案 b：语义/环边界
    #    距离/字号/穿墙遮挡，≥0.6 采纳，name_source=affinity_outside，
    #    低置信）——覆盖设计师把房间名写在环外空白区的制图习惯；
    #    评分也未采纳的环留 naming_hint，供 questions_to_confirm 提问。
    renamed, fallback_named, affinity_named = _disambiguate_room_names(
        rooms, texts, walls=walls)
    if renamed:
        base["limitations"].append(
            f"{renamed} 个闭环没有落在其内部的房间名文字且没有 2500mm 内的"
            "未占用兜底文字，已命名为“未命名空间”而非沿用远处/他环文字，需人工复核命名。")
    if fallback_named:
        base["limitations"].append(
            f"{fallback_named} 个闭环内部没有房间名文字，已用 2500mm 内最近的"
            "未被其他闭环占用的文字兜底命名（name_source=nearest_outside，低置信），"
            "需人工复核命名。")
    if affinity_named:
        base["limitations"].append(
            f"{affinity_named} 个闭环无环内文字且超出 2500mm 就近兜底范围，已按"
            "文字-环亲和度评分（语义词表/环边界距离/字号/穿墙遮挡）命名"
            "（name_source=affinity_outside，低置信），需人工复核命名。")

    # 虚拟桥接边界标记：含大洞口推断墙的房间降置信，供下游闸门区分。
    virtual_segments = result.get("virtual_segments") or []
    virtual_rooms = _mark_virtual_boundaries(rooms, virtual_segments, snap)
    if virtual_rooms:
        base["limitations"].append(
            f"以下房间的边界含虚拟桥接段（阳台/落地窗级大洞口的推断开口面）："
            f"{'、'.join(virtual_rooms)}。这些边界不是实墙证据，需人工复核。")
    base["virtual_walls"] = [(round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1))
                             for x1, y1, x2, y2 in virtual_segments]

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

    # ---------- 门洞语义分级（单图版；双图互证收敛在 plan_fusion 完成） ----------
    # doors 原始清单保持不变（零退化），door_details 是附加的语义视图：
    # 有门扇弧线佐证 → door（高置信）；仅有缺口 → opening（低置信、诚实降级）；
    # 不邻接任何空间的缺口标注为 unverified，供融合层剔除，单图路径不删。
    base["door_details"] = build_door_details(
        base["doors"], door_arcs, rooms, base["bounds"], calibrated,
        tick_gaps=base["jamb_tick_gaps"])

    # ---------- 置信度与限制 ----------
    base["confidence"] = _overall_confidence(
        calibrated, rooms, base["doors"], base["windows"],
        has_virtual=bool(virtual_rooms))
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

    # 未配对长单线分级（家具线条过滤的证据通道）：
    # 含家具的布置图里，床/沙发/柜体轮廓和尺寸标注线都是未配对单线。
    # 判别依据是与墙体网络的连接性（传递闭包）：真墙端点必然搭接到墙体
    # 网络——内隔墙常被设计师画成单线，它们彼此相连成网、最终接到墙中
    # 线上；家具/标注轮廓则是孤立的簇。从墙中线出发逐级吸收触碰网络的
    # 单线，直到收敛：
    # - 结构单线（接入墙体网络）：按墙体证据对待；
    # - 浮动单线（始终孤立，疑似家具/标注）：仍参与几何解析（真实图纸的
    #   散线墙也靠它们闭合），但全部留痕（furniture_lines），且由它们
    #   封口的洞口必须另有门扇/窗符号佐证（见 needs_proof 侧翼规则）、
    #   由它们主导的闭环按家具线过滤规则剔除（_furniture_room_reasons）。
    # 单线图纸（无双线墙）不启用本分级。
    structural_singles = []
    floating_singles = []
    if double_line_mode:
        candidates = []
        for i, s in enumerate(axis_segs):
            if s[8] or i in merged_idx:
                continue
            if s[3] - s[2] < min_wall:
                continue
            candidates.append(s)
        network = list(centerlines)
        remaining = list(candidates)
        changed = True
        while changed:
            changed = False
            keep = []
            for s in remaining:
                if _touches_wall_network(s, network, snap * 2):
                    structural_singles.append(s)
                    network.append(s)
                    changed = True
                else:
                    keep.append(s)
            remaining = keep
        floating_singles = remaining
        if floating_singles:
            notes.append(
                f"{len(floating_singles)} 条未接入墙体网络的未配对单线（疑似家具/陈设/"
                "标注轮廓）已标记留痕（furniture_lines）：由它们封口的洞口需门扇/窗符号"
                "佐证，由它们主导的闭环按家具线过滤剔除。")

    # 洞口检测的基底：双线模式用「墙中线 + 全部长单线」——中线保证门洞不被
    # 双面线重复计数，单线覆盖单线绘制的外墙/栏板（真实图纸常混用）；
    # 浮动单线仍在基底中（散线墙靠它们闭合），家具缝隙洞口由侧翼证据
    # 规则（needs_proof）拦截。
    if double_line_mode:
        gap_source = list(centerlines) + structural_singles + floating_singles
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
    # 洞口分级桥接（真实图纸的阳台推拉门/落地窗常超过门洞上限）：
    # - 门洞级（gap_range 内，≤2600mm）：正常桥接；
    # - 阳台/落地窗级（2600~4000mm，且簇内有墙中线佐证是真墙）：桥接但
    #   标记 virtual——这面墙是推断的开口面，下游按低置信度处理；
    # - 超大开口（>4000mm）：不桥接（露台/天井/开敞区），如实记录 limitation。
    centerline_ids = {id(c) for c in centerlines}
    clusters = _cluster_collinear(gap_source, snap)
    openings = []
    oversized_gaps = []
    for cluster in clusters:
        direction = cluster[0][0]
        line_coord = sum(s[1] for s in cluster) / len(cluster)
        has_center = any(id(s) in centerline_ids for s in cluster)
        runs = _merge_runs(sorted((s[2], s[3]) for s in cluster), snap)
        for (a1, b1), (a2, b2) in zip(runs, runs[1:]):
            gap = a2 - b1
            # 洞口侧翼来源：缺口两缘分别由哪类线段封口。两缘都是未配对单线
            # （而非墙中线）时，这个"洞口"其实是两件家具/符号之间的缝隙，
            # 即使所在共线簇里别处有墙中线，也必须有门扇/窗符号佐证才采信。
            left_flank = next((s for s in cluster if abs(s[3] - b1) <= snap), None)
            right_flank = next((s for s in cluster if abs(s[2] - a2) <= snap), None)
            flanked_by_singles = (
                left_flank is not None and right_flank is not None
                and id(left_flank) not in centerline_ids
                and id(right_flank) not in centerline_ids)
            if gap_range[0] <= gap <= gap_range[1]:
                openings.append({
                    "axis": direction,
                    "line": line_coord,
                    "gap_start": b1,
                    "gap_end": a2,
                    "width": gap,
                    "needs_proof": (not has_center) or flanked_by_singles,
                    "virtual": False,
                })
            elif calibrated and has_center and _BALCONY_GAP_MM[0] < gap <= _BALCONY_GAP_MM[1]:
                openings.append({
                    "axis": direction,
                    "line": line_coord,
                    "gap_start": b1,
                    "gap_end": a2,
                    "width": gap,
                    "needs_proof": False,
                    "virtual": True,
                })
            elif calibrated and has_center and _BALCONY_GAP_MM[1] < gap <= _OVERSIZED_GAP_MM:
                oversized_gaps.append(gap)

    doors = []
    windows = []
    virtual_count = 0
    virtual_segments = []
    tick_gaps = []
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

        # 窗槛短档（tick）：垂直于墙、跨过墙线、长度在墙厚量级（80–450mm）的
        # 短档线。真实结构图的窗表达常是"墙打断 + 洞口两端各一道短档"，
        # 没有覆盖洞口的平行长符号线——上面的平行线检测会漏。两端都有短档
        # 才是窗；门洞也可能有门框短档，但门另有门扇斜线/弧线佐证。
        tick_len = (80.0, 450.0) if calibrated else (6.0, 32.0)
        tick_snap = 150.0 if calibrated else 10.0
        cross = (60.0, 60.0) if calibrated else (4.0, 4.0)
        ticks = [False, False]  # [起点端, 终点端]
        for s in axis_segs:
            if s[8] or s[0] == opening["axis"]:
                continue
            seg_len = s[3] - s[2]
            if not (tick_len[0] <= seg_len <= tick_len[1]):
                continue
            if not (s[2] <= opening["line"] - cross[0]
                    and s[3] >= opening["line"] + cross[1]):
                continue  # 必须跨过墙线
            for end_idx, end_pos in ((0, opening["gap_start"]), (1, opening["gap_end"])):
                if abs(s[1] - end_pos) <= tick_snap:
                    ticks[end_idx] = True
        has_jamb_ticks = all(ticks)

        if opening.get("needs_proof") and not (symbol_segs or has_leaf):
            opening["rejected"] = True
            continue  # 纯单线簇的无佐证洞口：家具缺口/符号间隙，不桥接、不计数

        if has_jamb_ticks:
            tick_gaps.append((round(p1[0], 1), round(p1[1], 1),
                              round(p2[0], 1), round(p2[1], 1)))
        if not exterior:
            doors.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
        elif symbol_segs:
            for s in symbol_segs:
                s[8] = True  # 标记为窗符号，不再作为墙线
            windows.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
        elif opening.get("virtual"):
            # 阳台/落地窗级大洞口：按窗处理（采光面），桥接段标记为虚拟墙
            windows.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
        else:
            doors.append((round(p1[0], 1), round(p1[1], 1), round(p2[0], 1), round(p2[1], 1)))
            notes.append("外墙存在无窗符号的洞口，按门洞处理（可能是入户门/阳台门），需人工确认。")
        if opening.get("virtual"):
            virtual_count += 1
            virtual_segments.append((p1[0], p1[1], p2[0], p2[1]))

    # 墙线输出 + 洞口桥接段（供闭环检测把房间封合）
    walls = []
    if double_line_mode:
        # 双线模式：墙 = 合并出的中线 + 全部未配对长单线（单线外墙/栏板/
        # 散线内墙与家具/标注线都会进来——家具/标注主导的假房间在闭环后
        # 按物理下限与单线占比过滤，数值命名假房间与细条环一并剔除；
        # 中线短门槛段也保留，否则相邻门洞间的墙垛会漏）。
        min_center = 100.0 if calibrated else 8.0
        for c in centerlines:
            if c[3] - c[2] >= min_center:
                walls.append((c[4], c[5], c[6], c[7], 120))
        singles = 0
        for s in structural_singles + floating_singles:
            if s[8]:
                continue
            walls.append((s[4], s[5], s[6], s[7], 120))
            singles += 1
        if singles:
            notes.append(
                f"双线墙模式：另计入 {singles} 条未配对长单线（单线墙体/栏板/"
                "散线内墙，含疑似家具/标注线——其主导的假房间已在闭环后过滤），"
                "仍需人工复核。")
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
    if virtual_count:
        notes.append(
            f"{virtual_count} 个阳台/落地窗级大洞口（2600–4000mm，有墙线佐证）已桥接为"
            "虚拟墙：该边界是推断的开口面而非实墙，相关房间标记 virtual_boundary=True，"
            "整体置信度相应下调，需人工复核。")
    if oversized_gaps:
        notes.append(
            f"{len(oversized_gaps)} 个超过 4000mm 的超大开口（最大 {round(max(oversized_gaps))}mm）"
            "未桥接：可能是露台/天井/开敞区，其内侧空间无法闭环，未计入房间。")

    return {
        "walls": walls,
        "doors": doors,
        "windows": windows,
        "virtual_segments": virtual_segments,
        "tick_gaps": tick_gaps,
        # 全部未配对长单线（结构+浮动）：供闭环边界单线占比计算；
        # floating_singles 单列留痕（未参与洞口/闭环的家具/标注线）。
        "single_segments": [(s[4], s[5], s[6], s[7])
                            for s in structural_singles + floating_singles if not s[8]],
        "floating_singles": [(s[4], s[5], s[6], s[7])
                             for s in floating_singles if not s[8]],
        "unclassified_count": max(0, unclassified),
        "notes": notes,
    }


def _touches_wall_network(single, centerlines, tol):
    """单线任一端点是否落在某墙中线上（T 型搭接或端点相接）。

    真墙（含单线绘制的栏板/隔墙）端点必然与其他墙体相接；家具与标注
    轮廓整体漂浮在墙网之外。这是区分结构单线与家具线的几何依据。
    """
    for px, py in ((single[4], single[5]), (single[6], single[7])):
        for c in centerlines:
            if _point_seg_distance(px, py, (c[4], c[5], c[6], c[7])) <= tol:
                return True
    return False


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


def _weld_and_prune_for_faces(walls, snap):
    """图面清理（仅用于面遍历，不改变对外输出的墙线）。

    1. 端点量化到 snap 网格；
    2. 节点焊接：union-find 合并间距 ≤1 格的节点（40~100mm 的双线残余、
       错位 T 节点并为一个连接点）；
    3. 重建墙段 → 去自环、去重边 → T 型节点重切（端点落回线上）；
    4. 迭代剪掉悬挂墙头（死胡同）——焊接后节点连通可靠，剪枝安全：
       面遍历不再走进死胡同折返，也就不会产生不闭合的退化面。
    """
    # 1) 量化端点
    edges = []
    node_set = set()
    for x1, y1, x2, y2, _t in walls:
        p1 = (round(x1 / snap) * snap, round(y1 / snap) * snap)
        p2 = (round(x2 / snap) * snap, round(y2 / snap) * snap)
        if p1 == p2:
            continue
        edges.append((p1, p2))
        node_set.add(p1)
        node_set.add(p2)
    nodes = sorted(node_set)

    # 2) 焊接 ≤1 格（Chebyshev）的节点
    parent = {p: p for p in nodes}

    def find(p):
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            if b[0] - a[0] > snap:
                break  # 排序后剪枝（仅按 x 有序，够用）
            if abs(a[1] - b[1]) <= snap:
                union(a, b)
    clusters = {}
    for p in nodes:
        clusters.setdefault(find(p), []).append(p)
    rep = {}
    for root, members in clusters.items():
        mx = sum(p[0] for p in members) / len(members)
        my = sum(p[1] for p in members) / len(members)
        r = (round(mx / snap) * snap, round(my / snap) * snap)
        for p in members:
            rep[p] = r

    # 3) 重建 + 去自环/重边 + T 型重切（两轮，让切出的新节点再归并）
    wall_list = []
    for a, b in edges:
        ra, rb = rep[a], rep[b]
        if ra != rb:
            wall_list.append((ra[0], ra[1], rb[0], rb[1], 120))
    for _ in range(2):
        seen = set()
        unique = []
        for x1, y1, x2, y2, t in wall_list:
            p1 = (round(x1 / snap) * snap, round(y1 / snap) * snap)
            p2 = (round(x2 / snap) * snap, round(y2 / snap) * snap)
            if p1 == p2:
                continue
            key = (min(p1, p2), max(p1, p2))
            if key in seen:
                continue
            seen.add(key)
            unique.append((p1[0], p1[1], p2[0], p2[1], t))
        wall_list = _split_at_t_junctions(unique, snap)

    # 4) 迭代剪悬挂边（死胡同墙头）
    graph_edges = []
    for x1, y1, x2, y2, _t in wall_list:
        p1 = (round(x1 / snap) * snap, round(y1 / snap) * snap)
        p2 = (round(x2 / snap) * snap, round(y2 / snap) * snap)
        if p1 != p2:
            graph_edges.append((min(p1, p2), max(p1, p2)))
    graph_edges = list(set(graph_edges))
    while True:
        degree = {}
        for a, b in graph_edges:
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        kept = [(a, b) for a, b in graph_edges if degree[a] > 1 and degree[b] > 1]
        if len(kept) == len(graph_edges):
            break
        graph_edges = kept
    return [(a[0], a[1], b[0], b[1], 120) for a, b in graph_edges]


def _clean_and_validate_faces(rooms, walls, snap):
    """清理并校验面遍历结果，返回 (有效房间列表, 剔除数量)。

    真实 CAD 图纸的墙图含有大量悬挂墙头（门套线、台面线、符号残段），
    面遍历会走进死胡同再原路折返，多边形出现重复顶点。分两类处理：
    1. 墙头折返（A→B→A 式来回）：从顶点序列中剥除，得到真实边界环，
       并重算面积/周长——真实房间保留；
    2. 清理后仍有重复顶点（8 字自交）或闭合边在墙图中不存在的：
       退化闭环（墙缝、走廊描边），剔除。
    """
    edge_set = set()
    for x1, y1, x2, y2, _t in walls:
        p1 = (round(x1 / snap) * snap, round(y1 / snap) * snap)
        p2 = (round(x2 / snap) * snap, round(y2 / snap) * snap)
        if p1 != p2:
            edge_set.add((min(p1, p2), max(p1, p2)))
    kept = []
    dropped = 0
    for room in rooms:
        pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        if len(pts) < 3:
            dropped += 1
            continue
        # 剥除墙头折返：当前顶点的下一步若回到上上个顶点，说明上一段是
        # 死胡同往返，弹掉它（含首尾闭合边的折返）。
        stack = []
        for p in pts + [pts[0]]:
            if len(stack) >= 2 and stack[-2] == p:
                stack.pop()
            else:
                stack.append(p)
        if len(stack) >= 2 and stack[0] == stack[-1]:
            stack.pop()  # 去掉闭合重复点
        if len(stack) < 3 or len(set(stack)) != len(stack):
            dropped += 1  # 清理后仍有重复顶点（自交）或不足以成环
            continue
        ok = True
        for i in range(len(stack)):
            a, b = stack[i], stack[(i + 1) % len(stack)]
            if (min(a, b), max(a, b)) not in edge_set:
                ok = False
                break
        if not ok:
            dropped += 1
            continue
        if len(stack) != len(pts):
            # 边界有变化：重算面积与周长
            area = 0.0
            perimeter = 0.0
            for i in range(len(stack)):
                x1, y1 = stack[i]
                x2, y2 = stack[(i + 1) % len(stack)]
                area += x1 * y2 - x2 * y1
                perimeter += math.hypot(x2 - x1, y2 - y1)
            area_m2 = area / 2e6
            if not (0.5 < area_m2 < 500):
                dropped += 1
                continue
            room = dict(room)
            room["floor_points"] = [{"x": p[0], "y": p[1]} for p in stack]
            room["area_m2"] = round(area_m2, 2)
            room["perimeter_m"] = round(perimeter / 1000, 2)
        kept.append(room)
    return kept, dropped


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


_PDF_ROOM_KEYWORDS = ("客厅", "餐厅", "卧室", "厨房", "卫生间", "书房", "阳台",
                      "玄关", "储物", "衣帽", "走廊", "主卧", "次卧", "马桶", "卫")


def _relabel_rooms_by_inner_texts(rooms, texts):
    """按房间名文字的实际落点重命名/逻辑分区（PDF 路径专用）。

    cad_reader 的命名取"最近文字"，开敞空间里大闭环会偷走隔壁房间的名字。
    这里改为包含判断：
    - 环内有且仅有一个房间名 → 用它命名；
    - 环内有多个房间名（客餐厅一体、开放式厨房等开敞布局）→ 标注为复合空间
      （如 "客厅+餐厅"），文字位置写入 zones 作为逻辑分区，不伪造物理隔墙；
    - 环内没有房间名 → 保留最近文字命名结果不变。
    """
    name_texts = [t for t in texts
                  if any(k in (t.get("text") or "") for k in _PDF_ROOM_KEYWORDS)]
    composite_count = 0
    for room in rooms:
        poly = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        if len(poly) < 3:
            continue
        inside = []
        for t in name_texts:
            if _point_in_polygon(t["x"], t["y"], poly):
                if t["text"] not in [i["text"] for i in inside]:
                    inside.append(t)
        if len(inside) >= 2:
            room["name"] = "+".join(t["text"] for t in inside)
            room["composite"] = True
            room["zones"] = [{"name": t["text"], "x": round(t["x"], 1),
                              "y": round(t["y"], 1)} for t in inside]
            composite_count += 1
        elif len(inside) == 1:
            room["name"] = inside[0]["text"]
    return composite_count


# 环外亲和度命名（方案 b）：设计师常把房间名写到环外空白区（图面拥挤外溢、
# 成组命名、竖排贴边），单一距离阈值（2500mm）是对归属表达的过度简化。
# 评分只处理旧 2500mm 就近路径放弃的环，四分量可调，禁止按图纸特判。
_ROOM_NAME_LEXICON = ("客厅", "餐厅", "主卧", "次卧", "卧室", "厨房", "卫生间",
                      "书房", "阳台", "玄关", "走廊", "储物", "衣帽", "客卫", "主卫")
# 房间类型-面积物理先验（㎡ 上限，沿袭门宽 1.2m/净宽 1m 物理先验风格）：
# 实测"阳台"文字贴邻 22.8㎡ 客厅环（0 穿墙、1.2m）会被距离分满分误采纳——
# 距离/字号/遮挡四项挡不住"近但名实不符"，物理先验是唯一能干净区分的证据。
# 未列出的类型（客厅/餐厅/卧室/书房等）不设上限（无先验，不误伤）。
_ROOM_TYPE_MAX_AREA_M2 = {"阳台": 10.0, "玄关": 8.0, "走廊": 8.0, "储物": 8.0,
                          "衣帽": 8.0, "卫生间": 12.0, "客卫": 12.0, "主卫": 12.0,
                          "厨房": 15.0}
_AFFINITY_MAX_DIST_MM = 5000.0   # 文字到环边界距离上限（外溢命名可达 3m+）
_AFFINITY_ACCEPT_SCORE = 0.6     # 采纳门槛
_AFFINITY_W_SEMANTIC = 0.45      # 语义分权重（强房间词命中且类型-面积先验成立=1）
_AFFINITY_W_DIST = 0.30          # 距离分权重（1 - dist/5000）
_AFFINITY_W_FONT = 0.25          # 字号分权重（文字高/房间名中位字号，封顶 1）
_AFFINITY_OCCLUSION_PENALTY = 0.4  # 穿墙遮挡惩罚（连线穿过 ≥1 道墙线）
# 遮挡惩罚阈值 ≥1（方案草案为 ≥2，实施实测收紧）：正确候选是"贴邻环的空白区
# 文字"（0 穿墙），而罗菁平面图"主卧"@4.2m 仅穿 1 道墙（0.748）会被 ≥2 漏挡
# 造成基线漂移；≥1 在双图实测中正好把两类分开。


def _text_to_room_boundary(text, poly):
    """文字到闭环边界的最近距离与最近边界点（文字在环内时距离为 0）。

    到环边界（而非环心）的距离天然优待贴边外放的长条形/复合环——
    名字常被挤到大环边缘的空白区。
    """
    px, py = text["x"], text["y"]
    if _point_in_polygon(px, py, poly):
        return 0.0, (px, py)
    best_d, best_pt = None, None
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        seg_len2 = dx * dx + dy * dy
        t = 0.0 if seg_len2 == 0 else max(
            0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len2))
        qx, qy = x1 + t * dx, y1 + t * dy
        d = math.hypot(px - qx, py - qy)
        if best_d is None or d < best_d:
            best_d, best_pt = d, (qx, qy)
    return best_d, best_pt


def _count_wall_crossings(p1, p2, walls):
    """文字到环边界最近点的连线严格穿过的墙线数量（遮挡惩罚依据）。

    严格交叉（跨立实验，端点接触不算）——贴边文字的连线终点落在目标环
    边界墙上，不应把目标墙本身计入遮挡。
    """
    def _cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    count = 0
    for w in walls or []:
        p3, p4 = (w[0], w[1]), (w[2], w[3])
        d1 = _cross(p3, p4, p1)
        d2 = _cross(p3, p4, p2)
        d3 = _cross(p1, p2, p3)
        d4 = _cross(p1, p2, p4)
        if d1 * d2 < 0 and d3 * d4 < 0:
            count += 1
    return count


def _affinity_name_score(text, poly, walls, median_font_h, room_area_m2=None):
    """文字-环亲和度评分。返回 (score, evidence)；score ≥0.6 才采纳。

    score = 0.45·语义 + 0.30·(1−dist/5000) + 0.25·字号 − 0.4·(穿墙≥1)
    语义分：房间名词表命中且通过类型-面积物理先验（如阳台 ≤10㎡）=1，否则=0。
    """
    hit = any(k in (text.get("text") or "") for k in _ROOM_NAME_LEXICON)
    plausible = True
    if hit and room_area_m2:
        for k, max_area in _ROOM_TYPE_MAX_AREA_M2.items():
            if k in text["text"] and room_area_m2 > max_area:
                plausible = False  # 类型-面积物理先验不成立（如 22.8㎡ 环不是阳台）
                break
    semantic = 1.0 if (hit and plausible) else 0.0
    dist, near_pt = _text_to_room_boundary(text, poly)
    dist_score = max(0.0, 1.0 - dist / _AFFINITY_MAX_DIST_MM)
    font_h = text.get("height") or 0.0
    font_score = min(1.0, font_h / median_font_h) if median_font_h > 0 else 0.5
    crossings = _count_wall_crossings((text["x"], text["y"]), near_pt, walls)
    occlusion = _AFFINITY_OCCLUSION_PENALTY if crossings >= 1 else 0.0
    score = (_AFFINITY_W_SEMANTIC * semantic + _AFFINITY_W_DIST * dist_score
             + _AFFINITY_W_FONT * font_score - occlusion)
    evidence = {
        "semantic": semantic,
        "dist_mm": round(dist, 1),
        "font_h": round(font_h, 1),
        "median_font_h": round(median_font_h, 1),
        "wall_crossings": crossings,
    }
    return score, evidence


def _disambiguate_room_names(rooms, texts, far_threshold=2500.0, walls=None):
    """同名编号 + 命名环内优先/环外兜底诚实化。返回 (未命名数, 兜底命名数, 亲和命名数)。

    环内优先原则：落在任一闭环内部的房间名文字被该环"占用"，不再参与
    其他环的就近命名——就近匹配曾让环外名字贴到墙缝条带/家具碎片上
    （名实不符）。环内无文字的闭环只能用未被占用的文字兜底，且标低置信。

    环外兜底分两级（旧路径绝对优先，评分路径只处理旧路径放弃的环）：
    1) 2500mm 内最近未占用文字兜底（name_source=nearest_outside）；
    2) 文字-环亲和度评分（语义词表 + 到环边界距离 + 字号 + 穿墙遮挡惩罚，
       ≥0.6 采纳，name_source=affinity_outside）——覆盖设计师把房间名
       写在环外空白区（图面拥挤外溢）的制图习惯（如客厅名距厅环 3m）。
       评分也未采纳的环命名为"未命名空间"并留 naming_hint（最近未占用
       文字与距离/得分），供 questions_to_confirm 生成待确认问题。
    """
    name_texts = [t for t in texts
                  if any(k in (t.get("text") or "") for k in _PDF_ROOM_KEYWORDS)]
    heights = sorted(t.get("height") or 0.0 for t in name_texts)
    median_font_h = heights[len(heights) // 2] if heights else 0.0
    polys = []
    for room in rooms:
        polys.append([(p["x"], p["y"]) for p in room.get("floor_points") or []])
    claimed = set()  # 落在某闭环内部的文字：被该环占用，不再外借命名
    for t in name_texts:
        for poly in polys:
            if len(poly) >= 3 and _point_in_polygon(t["x"], t["y"], poly):
                claimed.add(id(t))
                break
    unnamed = 0
    fallback = 0
    affinity = 0
    for room, poly in zip(rooms, polys):
        if len(poly) < 3 or not name_texts:
            continue
        has_inner = any(_point_in_polygon(t["x"], t["y"], poly) for t in name_texts)
        if has_inner:
            continue
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        free = [t for t in name_texts if id(t) not in claimed]
        if not free:
            room["name"] = "未命名空间"
            unnamed += 1
            continue
        nearest_t = min(free, key=lambda t: math.hypot(t["x"] - cx, t["y"] - cy))
        nearest = math.hypot(nearest_t["x"] - cx, nearest_t["y"] - cy)
        if nearest <= far_threshold:
            room["name"] = nearest_t["text"]
            room["name_source"] = "nearest_outside"   # 环外兜底命名：低置信，需复核
            room["name_confidence"] = "low"
            fallback += 1
            continue
        # 亲和度评分路径：旧 2500mm 就近路径放弃的环才进入，不改变旧路径行为。
        best_t, best_score, best_ev = None, 0.0, None
        hint_t, hint_score, hint_ev = None, 0.0, None  # 语义有效最高分候选（提问线索）
        for t in free:
            score, ev = _affinity_name_score(t, poly, walls, median_font_h,
                                             room_area_m2=room.get("area_m2"))
            if score > best_score:
                best_t, best_score, best_ev = t, score, ev
            if ev["semantic"] == 1.0 and score > hint_score:
                hint_t, hint_score, hint_ev = t, score, ev
        if best_t is not None and best_score >= _AFFINITY_ACCEPT_SCORE:
            room["name"] = best_t["text"]
            room["name_source"] = "affinity_outside"   # 环外亲和度命名：低置信，需复核
            room["name_confidence"] = "low"
            room["name_affinity"] = dict(best_ev, score=round(best_score, 3))
            affinity += 1
        else:
            room["name"] = "未命名空间"
            room.pop("name_source", None)
            room.pop("name_confidence", None)
            # 提问线索取语义有效的最高分候选（而非被物理先验/遮挡压掉的
            # 最高分），使问题问"疑似客厅？"而非"疑似阳台？"。
            use_t, use_score, use_ev = (
                (hint_t, hint_score, hint_ev) if hint_t is not None
                else (best_t, best_score, best_ev))
            room["naming_hint"] = {
                "nearest_free_text": use_t["text"] if use_t else None,
                "affinity_score": round(use_score, 3),
                "dist_mm": use_ev["dist_mm"] if use_ev else None,
            }
            unnamed += 1
    # 同名闭环按面积降序编号（rooms 已是面积降序）
    counts = {}
    for room in rooms:
        name = room.get("name") or ""
        counts[name] = counts.get(name, 0) + 1
    seen = {}
    for room in rooms:
        name = room.get("name") or ""
        if counts.get(name, 0) > 1:
            seen[name] = seen.get(name, 0) + 1
            if seen[name] > 1:
                room["name"] = f"{name}{seen[name]}"
    return unnamed, fallback, affinity


def _furniture_room_reasons(room, w, d, single_segs, snap):
    """家具线条/物理下限检查（家具线过滤的闭环级兜底）。返回剔除理由（空=保留）。

    判别信号（只用能干净区分真假的证据，宁可少剔也不错杀）：
    - 物理下限：房间净宽 <1m 不可能是任何功能房间（条带/墙缝/符号描边）；
    - 面积 <3㎡ 且边界 ≥50% 由未配对浮动单线构成：家具描边小环
      （柜体/洁具轮廓；真实小房间的边界是墙中线/结构单线，浮动线占比低）。
    1.0~1.5m 窄带（走廊/凹位）单线占比真假混叠（实测真走廊 0.30~0.36、
    假条带 0.21），不做覆盖率剔除，避免误杀真实走廊。
    """
    reasons = []
    min_dim = min(w, d)
    area = room.get("area_m2", 0) or 0
    if min_dim < 1000.0:
        reasons.append(
            "净宽 %.2fm 低于 1m 物理下限：净宽 <1.5m 的闭环不是房间"
            "（多为墙缝条带或家具轮廓）" % (min_dim / 1000.0))
        return reasons
    cov = _boundary_single_coverage(room, single_segs, snap)
    if area < 3.0 and cov >= 0.5:
        reasons.append(
            "面积 %.2f㎡ 且边界 %.0f%% 为未配对浮动单线（家具/标注轮廓）："
            "家具描边小环" % (area, cov * 100))
    return reasons


def _boundary_single_coverage(room, single_segs, snap):
    """房间边界边长中被未配对单线覆盖的比例（按长度计）。"""
    if not single_segs:
        return 0.0
    pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
    total = 0.0
    covered = 0.0
    for i in range(len(pts)):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % len(pts)]
        elen = math.hypot(bx - ax, by - ay)
        if elen <= 0:
            continue
        total += elen
        edge_cov = 0.0
        for x1, y1, x2, y2 in single_segs:
            if abs(ay - by) <= snap and abs(y1 - y2) <= snap:
                if abs((ay + by) / 2 - (y1 + y2) / 2) > snap * 2:
                    continue
                ov = min(max(ax, bx), max(x1, x2)) - max(min(ax, bx), min(x1, x2))
            elif abs(ax - bx) <= snap and abs(x1 - x2) <= snap:
                if abs((ax + bx) / 2 - (x1 + x2) / 2) > snap * 2:
                    continue
                ov = min(max(ay, by), max(y1, y2)) - max(min(ay, by), min(y1, y2))
            else:
                continue
            if ov > 0:
                edge_cov += ov
        covered += min(edge_cov, elen)
    return covered / total if total else 0.0


def _mark_virtual_boundaries(rooms, virtual_segments, snap):
    """标记边界含虚拟桥接段（大洞口推断墙）的房间，返回受影响的房间名。

    房间面来自桥接后的墙图，逐边检查是否与虚拟段共线且有实质重合。
    """
    if not virtual_segments:
        return []
    marked = []
    for room in rooms:
        pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        hit = False
        for i in range(len(pts)):
            if hit:
                break
            ax, ay = pts[i]
            bx, by = pts[(i + 1) % len(pts)]
            for x1, y1, x2, y2 in virtual_segments:
                if abs(ay - by) <= snap and abs(y1 - y2) <= snap:
                    if abs((ay + by) / 2 - (y1 + y2) / 2) > snap:
                        continue
                    overlap = min(max(ax, bx), max(x1, x2)) - max(min(ax, bx), min(x1, x2))
                elif abs(ax - bx) <= snap and abs(x1 - x2) <= snap:
                    if abs((ax + bx) / 2 - (x1 + x2) / 2) > snap:
                        continue
                    overlap = min(max(ay, by), max(y1, y2)) - max(min(ay, by), min(y1, y2))
                else:
                    continue
                if overlap >= max(300.0, snap * 2):
                    hit = True
                    break
        if hit:
            room["virtual_boundary"] = True
            marked.append(room.get("name") or "未命名")
    return marked


def _overall_confidence(calibrated, rooms, doors, windows, has_virtual=False):
    if not calibrated:
        return 0.25
    if not rooms:
        return 0.5
    conf = 0.66
    if doors:
        conf = 0.7
    if doors and windows:
        conf = 0.72
    if has_virtual:
        # 含虚拟桥接边界（推断的开口面）：诚实下调一档
        conf = max(0.5, conf - 0.05)
    return conf


# ---------------------------------------------------------------- 门洞语义分级

_DOOR_WIDTH_MM = 1300.0        # 门洞宽上限（超过按 opening）
_DOOR_LEAF_MAX_MM = 1200.0     # 单扇室内门物理上限：超过此宽度的"门"物理上不
                               # 成立（推拉门/阳台口/并门误判），弧线佐证不晋升 door
_BOUNDARY_NEAR_MM = 400.0      # 洞口贴近房间边界的判定距离
_BOUNDARY_FAR_MM = 600.0       # 超过此距离不邻接任何空间：疑似标注线噪声
_ARC_MATCH_MM = 700.0          # 门扇弧线与洞口的匹配距离


def point_to_seg_dist(px, py, x1, y1, x2, y2):
    """点到线段距离（供门弧/房间边界匹配复用）。"""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (length * length)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def arc_matches_gap(arc, x1, y1, x2, y2, tol=_ARC_MATCH_MM):
    """门扇弧线是否佐证该洞口：铰链/门板端/关闭端任一点贴近洞口线段，
    且弧半径与洞口宽度同量级。宽缺口（>1300mm）可能是相邻多门并入，
    不套半径下限（由融合层按弧拆分）；半径超过洞口宽 2 倍则不可能。"""
    width = math.hypot(x2 - x1, y2 - y1)
    radius = arc.get("radius_mm") or 0.0
    if width > 0 and radius:
        if radius > 2.0 * width:
            return False
        if width <= _DOOR_WIDTH_MM and radius < 0.4 * width:
            return False
    for key in ("hinge", "leaf_tip", "closed"):
        pt = arc.get(key)
        if pt and point_to_seg_dist(pt[0], pt[1], x1, y1, x2, y2) <= tol:
            return True
    return False


def arc_gap_distance(arc, x1, y1, x2, y2):
    """弧线佐证点（铰链/门板端/关闭端）到洞口线段的最近距离。"""
    best = None
    for key in ("hinge", "leaf_tip", "closed"):
        pt = arc.get(key)
        if not pt:
            continue
        dist = point_to_seg_dist(pt[0], pt[1], x1, y1, x2, y2)
        if best is None or dist < best:
            best = dist
    return best if best is not None else 1e9


def rooms_near_gap(x1, y1, x2, y2, rooms, near=_BOUNDARY_NEAR_MM):
    """洞口中点到各房间边界的最小距离 ≤near 的房间名列表（连通房间候选）。"""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    hits = []
    for room in rooms:
        poly = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        if len(poly) < 3:
            continue
        best = min(
            point_to_seg_dist(mx, my, ax, ay, bx, by)
            for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1])
        )
        if best <= near:
            hits.append((best, room.get("name") or "未命名"))
    hits.sort()
    return [name for _, name in hits]


def build_door_details(doors, door_arcs, rooms, bounds, calibrated=True,
                       tick_gaps=None):
    """门洞语义分级（单图版）。

    每个洞口产出 {type, start, end, width_mm, exterior, connects, evidence,
    confidence}：
    - 有门扇弧线佐证且宽度 ≤1200mm（单扇室内门物理上限）→ door（0.75）；
    - 有弧线但宽度 >1200mm：物理上不可能是普通室内门（推拉门/阳台口/
      相邻洞口并入/家具弧误判）→ 降级 opening（0.4），留痕 wide_arc_downgrade；
    - 无弧线但宽度在门洞量级且邻接空间 → opening（0.5，诚实降级）；
    - 宽度超过门洞量级 → opening（0.45）；
    - 不邻接任何空间（>600mm）→ unverified（0.3，疑似标注线/符号间隙，
      单图路径不删除，留给融合层判定）。
    两端有窗槛短档的洞口在 evidence 记 jamb_ticks，供融合层判窗。
    """
    details = []
    edge_tol = 300.0 if calibrated else 1e9
    tick_set = set()
    for tx1, ty1, tx2, ty2 in tick_gaps or []:
        tick_set.add((round(tx1), round(ty1), round(tx2), round(ty2)))
    for idx, (x1, y1, x2, y2) in enumerate(doors):
        width = math.hypot(x2 - x1, y2 - y1)
        exterior = False
        if bounds and len(bounds) == 4:
            exterior = min(
                abs(y1 - bounds[1]), abs(y1 - bounds[3]),
                abs(x1 - bounds[0]), abs(x1 - bounds[2]),
            ) <= edge_tol
        connects = rooms_near_gap(x1, y1, x2, y2, rooms)
        arc = next((a for a in door_arcs
                    if arc_matches_gap(a, x1, y1, x2, y2)), None)
        evidence = ["wall_gap"]
        if arc:
            evidence.append("door_arc")
        if exterior:
            evidence.append("exterior_wall")
        if (round(x1), round(y1), round(x2), round(y2)) in tick_set:
            evidence.append("jamb_ticks")

        if arc and width <= _DOOR_LEAF_MAX_MM:
            dtype, conf = "door", 0.75
        elif arc:
            # 门宽物理先验：>1.2m 的"门"物理上不成立——弧线来自家具或相邻
            # 洞口被过度合并，弧线佐证不再晋升为 door，诚实降级并留痕。
            dtype, conf = "opening", 0.4
            evidence.append("wide_arc_downgrade")
        elif not connects:
            nearest = _nearest_room_distance(x1, y1, x2, y2, rooms)
            if nearest > _BOUNDARY_FAR_MM:
                dtype, conf = "unverified", 0.3
                evidence.append("no_adjacent_room")
            else:
                dtype, conf = "opening", 0.45
        elif width <= _DOOR_WIDTH_MM:
            dtype, conf = "opening", 0.5
        else:
            dtype, conf = "opening", 0.45
        details.append({
            "id": "gap_%d" % idx,
            "type": dtype,
            "start": [round(x1, 1), round(y1, 1)],
            "end": [round(x2, 1), round(y2, 1)],
            "width_mm": round(width, 1),
            "exterior": exterior,
            "connects": connects,
            "evidence": evidence,
            "confidence": conf,
            "source": "structure",
        })
    return details


def _nearest_room_distance(x1, y1, x2, y2, rooms):
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    best = None
    for room in rooms:
        poly = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        if len(poly) < 3:
            continue
        dist = min(
            point_to_seg_dist(mx, my, ax, ay, bx, by)
            for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1])
        )
        if best is None or dist < best:
            best = dist
    return best if best is not None else 1e9
