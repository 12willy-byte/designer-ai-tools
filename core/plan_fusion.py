"""双图融合 —— 结构图 + 平面布置图交叉验证合并。

设计师的实际工作方式是"结构图对照布置图"：结构图（原始图）墙体/尺寸可信，
平面布置图（带家具）补充结构图上没有隔墙/文字的空间（如主卧）和房间名。
本模块把两份 pdf_plan_reader 解析结果对齐后交叉验证合并为一份 plan：

1. 坐标对齐：两份图纸导出比例可能不同（真实样本差 3%），还可能有平移/
   旋转。用房间名/分区文字的对应点做相似变换拟合（旋转限 0/90/180/270，
   比例归一 + 平移），再用房间重叠做几何迭代精化；输出整体 IoU 等质量
   指标。对齐质量不达标则如实拒绝融合（回退为只用结构图），不乱合并。
2. 角色分工：结构图为主——墙体/房间边界/面积以它为准；平面图为辅——
   补充结构图缺位的命名空间（source=plan_only，置信度较低，需现场确认）。
3. 交叉验证：
   - 双源一致（面积差 ≤15%）→ source=merged，置信度提升（有依据的升档）；
   - 双源矛盾 → 取结构图值，如实写入 conflicts；
   - 仅平面图有且落在结构图某空间内部的命名空间（如主卧）→ 合并为
     plan_only；无名/重名的小环判定为家具假环剔除；
   - 仅结构图有 → 原样保留（source=structure）。

诚实原则：提升的置信度只给双源一致的空间；冲突全部写进输出；对齐失败
就拒绝融合。输出与 cad_plan/pdf_plan 同构，可直接进入 space_profile
融合通道与自动化闸门。
"""
import copy
import math
import re


SCHEMA_VERSION = "plan_fusion.v1"

# ---- 对齐质量门槛 ----
_ROTATIONS = (0, 90, 180, 270)
_CELL_MM = 100.0                 # 光栅化 IoU 网格边长
_IOU_ACCEPT = 0.25               # 整体房间 IoU 下限
_PAIR_IOU_ACCEPT = 0.30          # 至少一对匹配房间的 IoU 下限
_RESIDUAL_ACCEPT_MM = 1000.0     # 名称对应点残差 RMS 上限

# ---- 匹配/判定阈值 ----
_PAIR_OVERLAP_MIN = 0.5          # 同一空间：交集/较小面积
_PAIR_AREA_RATIO = (0.45, 2.2)   # 同一空间：两图面积比合理区间
_CONTAIN_MIN = 0.6               # 平面图空间落入结构图空间的包含度
_CONSISTENT_AREA_TOL = 0.15      # 双源一致的面积差容忍
_PLAN_ONLY_MIN_AREA = 2.0        # plan_only 合并的最小面积（㎡）
_FURNITURE_MAX_RATIO = 0.25      # 家具假环：面积 ≤ 容器房间的 25%

# ---- 置信度模型 ----
_CONF_BOOST_DUAL = 0.15          # 双源一致的房间置信度提升
_CONF_ROOM_CAP = 0.9
_CONF_PLAN_ONLY = 0.5            # plan_only 房间置信度（低于双源/结构）
_CONF_VIRTUAL_PENALTY = 0.05     # 含虚拟桥接边界的房间降档
_CONF_OVERALL_STEP = 0.02        # 每个双源一致空间给整体置信度的加成
_CONF_OVERALL_CAP = 0.75


def fuse_plans(structure_plan, furnished_plan,
               iou_accept=_IOU_ACCEPT, pair_iou_accept=_PAIR_IOU_ACCEPT):
    """结构图 + 平面布置图交叉验证融合。

    Args:
        structure_plan: pdf_plan_reader 解析的结构图结果（为主）。
        furnished_plan: pdf_plan_reader 解析的平面布置图结果（为辅）。
    Returns:
        与 cad_plan/pdf_plan 同构的 dict：结构图原样拷贝 + 融合后的
        detected_rooms（每房间带 source/confidence）+ "fusion" 块
        （对齐指标、conflicts、剔除清单、统计）。对齐失败时 rooms 保持
        结构图原样、fusion.alignment.accepted=False，并在 limitations
        如实说明——调用方可透明地当作"只用结构图"继续。
    """
    fused = copy.deepcopy(structure_plan)
    fused["schema_version"] = SCHEMA_VERSION
    fused["source_type"] = "pdf_fusion"
    fusion = {
        "schema_version": SCHEMA_VERSION,
        "structure_source": structure_plan.get("source", ""),
        "plan_source": furnished_plan.get("source", ""),
        "role": "结构图为主（墙体/边界/面积以它为准），平面布置图为辅（补充命名空间）",
        "alignment": {"accepted": False},
        "conflicts": [],
        "filtered_furniture_rings": [],
        "zone_subdivisions": [],
        "stats": {},
    }
    fused["fusion"] = fusion

    s_rooms = [r for r in structure_plan.get("detected_rooms") or []
               if len(r.get("floor_points") or []) >= 3]
    p_rooms = [r for r in furnished_plan.get("detected_rooms") or []
               if len(r.get("floor_points") or []) >= 3]

    if not s_rooms or not p_rooms:
        fusion["alignment"]["reason"] = "其中一份图纸没有可用房间闭环，无法对齐。"
        fused["limitations"] = list(fused.get("limitations") or []) + [
            "双图融合未执行：其中一份图纸没有可用房间闭环，已回退为仅使用结构图。"]
        _label_structure_rooms(fused)
        return fused

    # ---------- 1. 坐标对齐 ----------
    alignment = _align(structure_plan, furnished_plan, s_rooms, p_rooms)
    fusion["alignment"] = alignment
    if (not alignment.get("accepted") or alignment["overall_iou"] < iou_accept
            or alignment.get("best_pair_iou", 0) < pair_iou_accept):
        alignment["accepted"] = False
        alignment.setdefault("reason", "对齐质量不达标（整体 IoU 或匹配对 IoU 低于门槛），"
                                       "两份图纸可能不是同一户型或图面差异过大。")
        fused["limitations"] = list(fused.get("limitations") or []) + [
            "双图融合被拒绝：%s已回退为仅使用结构图解析结果，平面布置图信息未并入。"
            % alignment["reason"]]
        _label_structure_rooms(fused)
        return fused

    # ---------- 2/3. 匹配 + 交叉验证合并 ----------
    _merge_and_validate(fused, structure_plan, furnished_plan, s_rooms, alignment)

    # ---------- 3.5 门语义跨图收敛 ----------
    _fuse_doors(fused, structure_plan, furnished_plan, alignment)

    # ---------- 4. 输出收尾 ----------
    fused["limitations"] = list(fused.get("limitations") or []) + fusion.pop("limitations_out")
    n_consistent = fusion["stats"].get("consistent", 0)
    base_conf = structure_plan.get("confidence")
    if base_conf:
        fused["confidence"] = round(
            min(_CONF_OVERALL_CAP, base_conf + _CONF_OVERALL_STEP * n_consistent), 2)
    return fused


# ---------------------------------------------------------------- 对齐

def _align(structure_plan, furnished_plan, s_rooms, p_rooms):
    """相似变换对齐（旋转 0/90/180/270 + 比例 + 平移），输出质量指标。

    鲁棒性设计（真实图纸的锚点很脏：文字位置/房间质心可能差出 1–2m）：
    - 比例不自由拟合：以两图 pt→mm 校准比为先验，精化时只允许在其
      ±10% 内微调——两份图纸各自校准过，比例差 3% 这种量级由先验承担，
      自由拟合会被脏锚点带飞；
    - 平移用锚点偏移的**中位数**（3 个锚点里 1 个跑偏不影响结果）；
    - 旋转不按锚点残差选，而是 4 个候选各自做几何迭代精化后按
      **房间重叠质量**（匹配对数 + 整体 IoU）选——几何一致才是真的对齐。
    """
    s_pts = _named_points(s_rooms)
    p_pts = _named_points(p_rooms)
    common = sorted(set(s_pts) & set(p_pts))
    k_prior = _scale_prior(structure_plan, furnished_plan)

    best = None
    for deg in _ROTATIONS:
        transform = _initial_transform(s_rooms, p_rooms, common, s_pts, p_pts,
                                       deg, k_prior)
        quality = None
        for _ in range(3):
            moved = _transform_rooms(p_rooms, transform)
            quality = _match_quality(s_rooms, moved)
            transform = _refine_transform(transform, quality, s_rooms, p_rooms,
                                          k_prior)
            if transform is None:
                break
        if transform is None:  # 精化发散（没有可用重叠对）
            moved = _transform_rooms(p_rooms,
                                     _initial_transform(s_rooms, p_rooms, common,
                                                        s_pts, p_pts, deg, k_prior))
            quality = _match_quality(s_rooms, moved)
            transform = _initial_transform(s_rooms, p_rooms, common,
                                           s_pts, p_pts, deg, k_prior)
        good_pairs = sum(1 for pair in quality["pairs"]
                         if pair["inter_ratio"] >= _PAIR_OVERLAP_MIN)
        score = (good_pairs, quality["overall_iou"])
        if best is None or score > best[0]:
            best = (score, deg, transform, quality)

    (_score, deg, transform, quality) = best
    moved = _transform_rooms(p_rooms, transform)
    residual = _anchor_residual(common, s_pts, p_pts, transform)
    result = {
        "accepted": True,
        "method": "相似变换（旋转枚举 + 校准比先验 + 中位数平移 + 房间重叠迭代精化）",
        "scale": round(transform[0], 6),
        "scale_prior": round(k_prior, 6),
        "rotation_deg": deg,
        "translation_mm": [round(transform[2], 1), round(transform[3], 1)],
        "correspondences": len(common),
        "anchor_names": common,
        "residual_rms": round(residual, 1),
        "overall_iou": quality["overall_iou"],
        "best_pair_iou": max((p["iou"] for p in quality["pairs"]), default=0.0),
        "matched_pairs": quality["pairs"],
    }
    if abs(transform[0] / k_prior - 1) > 0.08:
        result["scale_warning"] = (
            "精化后比例系数 %.4f 偏离校准比先验 %.4f 超过 8%%，对齐需人工复核。"
            % (transform[0], k_prior))
    if common and residual > _RESIDUAL_ACCEPT_MM:
        result["anchor_warning"] = (
            "名称锚点残差 RMS %dmm 偏大（文字落点/空间形心不在同一位置），"
            "对齐以房间重叠几何为准。" % round(residual))
    return result


def _initial_transform(s_rooms, p_rooms, common, s_pts, p_pts, deg, k_prior):
    """初始变换：比例=校准比先验；平移=锚点偏移中位数（无锚点则包围盒中心对齐）。"""
    if common:
        offsets = []
        for name in common:
            rx, ry = _rotate(p_pts[name], deg)
            offsets.append((s_pts[name][0] - k_prior * rx,
                            s_pts[name][1] - k_prior * ry))
        tx = _median([o[0] for o in offsets])
        ty = _median([o[1] for o in offsets])
        return (k_prior, deg, tx, ty)

    def center(rooms):
        xs = [p["x"] for r in rooms for p in r["floor_points"]]
        ys = [p["y"] for r in rooms for p in r["floor_points"]]
        return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    sc = center(s_rooms)
    rpc = _rotate(center(p_rooms), deg)
    return (k_prior, deg, sc[0] - k_prior * rpc[0], sc[1] - k_prior * rpc[1])


def _refine_transform(transform, quality, s_rooms, p_rooms, k_prior):
    """用重叠房间对精化比例/平移（旋转不变）。返回新变换；无重叠对返回 None。"""
    k, deg, tx, ty = transform
    pairs = [pair for pair in quality["pairs"] if pair["inter_ratio"] >= 0.3]
    if not pairs:
        return None
    offsets = []
    scale_ratios = []
    for pair in pairs:
        s_c = _centroid(_poly(s_rooms[pair["s_idx"]]))
        p_c = _centroid(_poly(p_rooms[pair["p_idx"]]))
        rx, ry = _rotate(p_c, deg)
        offsets.append((s_c[0] - k * rx - tx, s_c[1] - k * ry - ty))
        a_s = pair["structure_area_m2"]
        a_p_orig = (p_rooms[pair["p_idx"]].get("area_m2") or 0) * k * k
        # 只有"等量级"匹配对才参与比例精化：复合空间这类两图本来就不是
        # 同一口径（63㎡ vs 32㎡）的对会把比例带飞
        if a_s > 0 and a_p_orig > 0 and 0.7 <= a_s / a_p_orig <= 1.4:
            scale_ratios.append(math.sqrt(a_s / a_p_orig))
    tx += _median([o[0] for o in offsets])
    ty += _median([o[1] for o in offsets])
    if scale_ratios:
        k_new = k * _median(scale_ratios)
        # 比例只允许在校准比先验 ±5% 内微调，防止被脏匹配带飞
        k = min(max(k_new, k_prior * 0.95), k_prior * 1.05)
    return (k, deg, tx, ty)


def _anchor_residual(common, s_pts, p_pts, transform):
    """变换后名称锚点的 RMS 残差（报告用指标，不参与旋转选择）。"""
    if not common:
        return 0.0
    k, deg, tx, ty = transform
    total = 0.0
    for name in common:
        rx, ry = _rotate(p_pts[name], deg)
        dx = k * rx + tx - s_pts[name][0]
        dy = k * ry + ty - s_pts[name][1]
        total += dx * dx + dy * dy
    return math.sqrt(total / len(common))


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def _scale_prior(structure_plan, furnished_plan):
    """比例先验。

    关键事实：两份图纸若都已校准（dimensions_calibrated），坐标都已换算成
    真值 mm，几何本就在同一坐标系——先验应为 1.0。两份图 pt→mm 系数差 3%
    是因为导出纸张比例不同，不是几何差 3%，直接拿系数比当先验反而引入
    3% 系统误差。只有一方未校准（坐标仍是 pt）时才用系数比兜底。
    """
    s_pdf = structure_plan.get("pdf") or {}
    p_pdf = furnished_plan.get("pdf") or {}
    if s_pdf.get("dimensions_calibrated") and p_pdf.get("dimensions_calibrated"):
        return 1.0
    s_f = s_pdf.get("pt_to_mm") or 1.0
    p_f = p_pdf.get("pt_to_mm") or 1.0
    if p_f > 0:
        return s_f / p_f
    return 1.0


def _named_points(rooms):
    """提取命名锚点：复合空间的分区文字位置 + 非复合房间的质心。"""
    pts = {}
    for room in rooms:
        for zone in room.get("zones") or []:
            name = (zone.get("name") or "").strip()
            if name and _genuine(name) and name not in pts:
                pts[name] = (zone["x"], zone["y"])
        name = (room.get("name") or "").strip()
        if name and _genuine(name) and not room.get("composite") and name not in pts:
            pts[name] = _centroid(_poly(room))
    return pts


def _match_quality(s_rooms, moved_p_rooms):
    """光栅化计算整体 IoU 与每对候选匹配的重叠指标。"""
    polys = [_poly(r) for r in s_rooms] + [_poly(r) for r in moved_p_rooms]
    x0 = min(p[0] for poly in polys for p in poly)
    y0 = min(p[1] for poly in polys for p in poly)
    s_cells = [_rasterize(poly, x0, y0) for poly in polys[:len(s_rooms)]]
    p_cells = [_rasterize(poly, x0, y0) for poly in polys[len(s_rooms):]]

    pairs = []
    for si, sc in enumerate(s_cells):
        best = None
        for pi, pc in enumerate(p_cells):
            inter = len(sc & pc)
            if not inter:
                continue
            if best is None or inter > best[0]:
                best = (inter, pi)
        if not best:
            continue
        inter, pi = best
        union = len(sc | p_cells[pi])
        # 面积用多边形真值：100mm 光栅对窄条空间（衣帽间/阳台条带）系统性偏小，
        # 拿它做面积比对会把真实一致误判成冲突
        a_s = s_rooms[si].get("area_m2") or len(sc) * _CELL_MM ** 2 / 1e6
        a_p = moved_p_rooms[pi].get("area_m2") or len(p_cells[pi]) * _CELL_MM ** 2 / 1e6
        pairs.append({
            "s_idx": si,
            "p_idx": pi,
            "structure": s_rooms[si].get("name") or "未命名",
            "plan": moved_p_rooms[pi].get("name") or "未命名",
            "iou": round(inter / union, 3) if union else 0.0,
            "inter_ratio": round(inter / min(len(sc), len(p_cells[pi])), 3),
            "containment": round(inter / len(p_cells[pi]), 3),
            "inter_m2": round(inter * _CELL_MM ** 2 / 1e6, 2),
            "structure_area_m2": round(a_s, 2),
            "plan_area_m2": round(a_p, 2),
        })

    union_s = set().union(*s_cells) if s_cells else set()
    union_p = set().union(*p_cells) if p_cells else set()
    both = union_s & union_p
    overall = len(both) / len(union_s | union_p) if (union_s or union_p) else 0.0
    return {"pairs": pairs, "overall_iou": round(overall, 3)}


# ---------------------------------------------------------------- 合并与交叉验证

def _merge_and_validate(fused, structure_plan, furnished_plan, s_rooms, alignment):
    """交叉验证合并：改写 fused 的 detected_rooms，填充 fusion 块。

    以**平面图空间为主语**做全量重叠矩阵分类（而不是按结构图房间的最佳
    匹配）——结构图侧最佳匹配只能覆盖每房间一个配对，平面图的厨房/小环
    若不是任何结构图房间的"最佳"就会漏判；以平面图空间为主语逐个分类，
    每个平面图空间恰好落进一个类别：双源互证 / 容器内新空间(plan_only) /
    同名分区 / 家具假环 / 关系不明 / 无对应。
    """
    fusion = fused["fusion"]
    transform = (alignment["scale"], alignment["rotation_deg"],
                 *alignment["translation_mm"])
    p_rooms = [r for r in furnished_plan.get("detected_rooms") or []
               if len(r.get("floor_points") or []) >= 3]
    moved = _transform_rooms(p_rooms, transform)

    # 统一光栅化（共享原点），计算每个平面图空间对所有结构图空间的交集
    polys = [_poly(r) for r in s_rooms] + [_poly(r) for r in moved]
    x0 = min(p[0] for poly in polys for p in poly)
    y0 = min(p[1] for poly in polys for p in poly)
    s_cells = [_rasterize(poly, x0, y0) for poly in polys[:len(s_rooms)]]
    p_cells = [_rasterize(poly, x0, y0) for poly in polys[len(s_rooms):]]

    limitations = []
    conflicts = fusion["conflicts"]
    filtered = fusion["filtered_furniture_rings"]
    subdivisions = fusion["zone_subdivisions"]
    stats = {"structure_rooms": len(s_rooms), "plan_rooms": len(moved),
             "merged": 0, "consistent": 0, "structure_only": 0,
             "plan_only": 0, "filtered": 0, "zone_subdivision": 0}

    base_conf = structure_plan.get("confidence") or 0.6
    room_updates = {}    # s_idx -> (source, confidence, extra)
    plan_only_idx = []

    # ---- 第一遍：计算每个平面图空间的最佳结构图重叠与指标 ----
    metrics = []
    for p_idx, pc in enumerate(p_cells):
        p_room = moved[p_idx]
        a_p = p_room.get("area_m2") or len(pc) * _CELL_MM ** 2 / 1e6
        best = None
        for s_idx, sc in enumerate(s_cells):
            inter = len(pc & sc)
            if inter and (best is None or inter > best[0]):
                best = (inter, s_idx)
        entry = {"p_idx": p_idx, "a_p": a_p, "inter": 0, "s_idx": None,
                 "iou": 0.0, "inter_ratio": 0.0, "containment": 0.0, "cover": 0.0}
        if best:
            inter, s_idx = best
            sc = s_cells[s_idx]
            union = len(pc | sc)
            entry.update({
                "inter": inter, "s_idx": s_idx,
                "iou": round(inter / union, 3) if union else 0.0,
                "inter_ratio": inter / min(len(pc), len(sc)) if min(len(pc), len(sc)) else 0,
                "containment": inter / len(pc) if pc else 0,
                "cover": inter / len(sc) if sc else 0,
            })
        metrics.append(entry)

    # ---- 第二遍：同一空间配对（每个结构图房间只配一个平面图空间，交集大者胜）----
    paired_p = set()
    candidates = []
    for entry in metrics:
        if entry["s_idx"] is None or entry["inter_ratio"] < _PAIR_OVERLAP_MIN:
            continue
        s_room = s_rooms[entry["s_idx"]]
        p_room = moved[entry["p_idx"]]
        a_s = s_room.get("area_m2") or 0.01
        s_names = _room_name_set(s_room)
        p_names = _room_name_set(p_room)
        # 同一空间：几何互叠过半 +（面积同量级 或 名字集合有交集且平面图空间
        # 覆盖了结构图空间的可观部分）。名字救援要求 cover≥0.3：防止厨房2
        # 这类同名小分区借名字抢走整个复合空间的配对。
        if _PAIR_AREA_RATIO[0] <= entry["a_p"] / a_s <= _PAIR_AREA_RATIO[1] \
                or ((s_names & p_names) and entry["cover"] >= 0.3):
            candidates.append(entry)
    candidates.sort(key=lambda e: -e["inter"])
    used_s = set()
    for entry in candidates:
        if entry["s_idx"] in used_s:
            continue
        used_s.add(entry["s_idx"])
        paired_p.add(entry["p_idx"])
        s_idx = entry["s_idx"]
        s_room = s_rooms[s_idx]
        p_room = moved[entry["p_idx"]]
        a_s = s_room.get("area_m2") or 0.01
        a_p = entry["a_p"]
        p_base = _canonical(p_room.get("name"))
        conf = _room_conf(base_conf, s_room)
        diff = abs(a_p - a_s) / a_s
        if diff <= _CONSISTENT_AREA_TOL:
            room_updates[s_idx] = (
                "merged", min(_CONF_ROOM_CAP, conf + _CONF_BOOST_DUAL),
                {"plan_area_m2": a_p, "fusion_iou": entry["iou"]})
            stats["merged"] += 1
            stats["consistent"] += 1
            # 结构图无名而平面图有名：采用平面图命名（如实记录）
            if not _genuine(_canonical(s_room.get("name"))) and _genuine(p_base):
                room_updates[s_idx][2]["renamed_from"] = s_room.get("name")
                room_updates[s_idx][2]["name"] = p_base
                conflicts.append({
                    "type": "name_adopted", "room": p_base,
                    "structure_value": s_room.get("name"),
                    "plan_value": p_base,
                    "resolution": "结构图该闭环无命名，采用平面布置图名称，需人工复核。",
                })
        else:
            room_updates[s_idx] = ("structure", conf,
                                   {"plan_area_m2": a_p, "fusion_iou": entry["iou"]})
            stats["merged"] += 1
            conflicts.append({
                "type": "area_mismatch",
                "room": s_room.get("name") or "未命名",
                "structure_value": a_s, "plan_value": a_p,
                "iou": entry["iou"],
                "resolution": "两图同一空间面积差异 %.0f%%，以结构图为准。" % (diff * 100),
            })

    # ---- 第三遍：未配对平面图空间的包含/部分重叠/无对应分类 ----
    for entry in metrics:
        p_idx = entry["p_idx"]
        if p_idx in paired_p:
            continue
        p_room = moved[p_idx]
        a_p = entry["a_p"]
        p_base = _canonical(p_room.get("name"))
        p_names = _room_name_set(p_room)
        if entry["s_idx"] is not None:
            s_room = s_rooms[entry["s_idx"]]
            a_s = s_room.get("area_m2") or 0.01
            s_names = _room_name_set(s_room)
            if entry["containment"] >= _CONTAIN_MIN:
                # 平面图空间基本落在结构图某空间内部
                if not _genuine(p_base):
                    pass  # 无名小环 → 下面按家具环处理
                elif (p_names & s_names) and a_p < _PLAN_ONLY_MIN_AREA:
                    pass  # 同名分区但过小（厨房2 之类）→ 按家具环处理
                elif p_names & s_names:
                    subdivisions.append({
                        "name": p_room.get("name"), "area_m2": round(a_p, 2),
                        "container": s_room.get("name") or "未命名",
                        "note": "平面图该闭环是结构图空间内同名分区的独立表达，"
                                "面积口径不同，不重复计入。",
                    })
                    stats["zone_subdivision"] += 1
                    continue
                elif a_p >= _PLAN_ONLY_MIN_AREA:
                    plan_only_idx.append(p_idx)
                    continue
                if a_p <= _FURNITURE_MAX_RATIO * a_s or a_p < _PLAN_ONLY_MIN_AREA:
                    filtered.append({
                        "name": p_room.get("name") or "未命名", "area_m2": round(a_p, 2),
                        "container": s_room.get("name") or "未命名",
                        "reason": "落在结构图已知空间内部且面积小（%.1f㎡ ≤ 容器 %.0f㎡ 的 %d%%），"
                                  "判定为家具/符号假环剔除。"
                                  % (a_p, a_s, round(_FURNITURE_MAX_RATIO * 100)),
                    })
                    stats["filtered"] += 1
                else:
                    conflicts.append({
                        "type": "unclassified_inner_ring",
                        "room": p_room.get("name") or "未命名",
                        "structure_value": s_room.get("name"), "plan_value": round(a_p, 2),
                        "resolution": "平面图空间落在结构图空间内部但既非同名分区也非小家具环，"
                                      "关系不明确：未并入，以结构图为准，需人工复核。",
                    })
                continue
            if entry["inter_ratio"] >= 0.3 or entry["containment"] >= 0.3:
                conflicts.append({
                    "type": "partial_overlap",
                    "room": p_room.get("name") or "未命名",
                    "structure_value": s_room.get("name") or "未命名",
                    "plan_value": round(a_p, 2),
                    "iou": entry["iou"],
                    "resolution": "两图空间部分重叠但不足以判定为同一空间或包含关系，"
                                  "未并入，以结构图为准，需人工复核。",
                })
                continue
        # 与结构图任何空间都无可采信对应
        if _genuine(p_base) and a_p >= _PLAN_ONLY_MIN_AREA:
            plan_only_idx.append(p_idx)
        else:
            filtered.append({
                "name": p_room.get("name") or "未命名", "area_m2": round(a_p, 2),
                "container": None,
                "reason": "与结构图任何空间都无对应且无名/过小，判定为家具/符号假环剔除。",
            })
            stats["filtered"] += 1

    # ---- 改写 fused 房间清单 ----
    out_rooms = []
    for s_idx, room in enumerate(fused.get("detected_rooms") or []):
        if len(room.get("floor_points") or []) < 3:
            continue
        if s_idx in room_updates:
            source, conf, extra = room_updates[s_idx]
            room["source"] = source
            room["confidence"] = round(conf, 2)
            room.update(extra)
        else:
            room["source"] = "structure"
            room["confidence"] = round(_room_conf(base_conf, room), 2)
            stats["structure_only"] += 1
        out_rooms.append(room)

    plan_only_names = []
    for p_idx in plan_only_idx:
        p_room = copy.deepcopy(moved[p_idx])
        a_p = round(_poly_area_m2(_poly(p_room)), 2)
        p_room["area_m2"] = a_p
        p_room["perimeter_m"] = round(_poly_perimeter_m(_poly(p_room)), 2)
        p_room["source"] = "plan_only"
        p_room["confidence"] = _CONF_PLAN_ONLY
        p_room["needs_site_verification"] = True
        p_room["fusion_note"] = ("该空间仅见于平面布置图：结构图上无对应隔墙/文字，"
                                 "面积与边界以平面图为准，需现场确认。")
        out_rooms.append(p_room)
        plan_only_names.append("%s %.1f㎡" % (p_room.get("name") or "未命名", a_p))
        stats["plan_only"] += 1

    fused["detected_rooms"] = out_rooms
    fusion["stats"] = stats
    fusion["limitations_out"] = limitations

    # ---- 汇总 limitations（诚实完整）----
    limitations.append(
        "已与平面布置图交叉验证融合：%d 个空间双源互证（%d 个一致已升置信、%d 个有出入"
        "以结构图为准并记入 conflicts），%d 个空间仅平面图有（source=plan_only、置信度 "
        "%.1f、需现场确认），%d 个家具/符号假环剔除。"
        % (stats["merged"], stats["consistent"], stats["merged"] - stats["consistent"],
           stats["plan_only"], _CONF_PLAN_ONLY, stats["filtered"]))
    limitations.append(
        "双图对齐：旋转 %d°、比例系数 %.4f、平移 (%.0f, %.0f)mm，整体房间 IoU %.2f。"
        % (alignment["rotation_deg"], alignment["scale"],
           alignment["translation_mm"][0], alignment["translation_mm"][1],
           alignment["overall_iou"]))
    if plan_only_names:
        limitations.append(
            "以下空间仅见于平面布置图（结构图无隔墙/文字佐证），已按 plan_only 纳入，"
            "需现场确认：" + "、".join(plan_only_names) + "。")
    if stats["structure_only"]:
        limitations.append(
            "%d 个空间仅结构图有（平面图未闭合对应区域），保持结构图结果不变。"
            % stats["structure_only"])


# ---------------------------------------------------------------- 门语义收敛

# ---- 门收敛阈值 ----
_DOOR_DUP_LINE_MM = 250.0      # 双线墙重复洞口：线距上限
_DOOR_DUP_OVERLAP = 0.6        # 双线墙重复洞口：跨度重叠率
_DOOR_ARC_TOL_MM = 750.0       # 门扇弧线与洞口的匹配距离
_DOOR_FAR_MM = 600.0           # 距任何空间边界超过此值：标注线噪声
_DOOR_WIDTH_MAX_MM = 1300.0    # 门洞宽上限
_WINDOW_TICK_MIN_W_MM = 1200.0 # 窗槛短档洞口判窗的宽度下限
_LARGE_OPENING_MM = 2000.0     # 超过此宽度：开敞连通口/飘窗面，不计入门集合


def _fuse_doors(fused, structure_plan, furnished_plan, alignment):
    """门语义跨图融合：结构图缺口 × 双图门扇弧线互证，收敛门集合。

    输入证据：
    - 结构图洞口（pdf_plan_reader 缺口启发式，噪声多但覆盖全）；
    - 双图门扇弧线（内容流级提取的门符号：铰链+半径+门板端，最强语义）；
    - 窗槛短档标记（jamb_ticks，窗的候选特征）；
    - 融合后房间的边界邻接（连通房间）。

    判定（诚实优先，宁可 opening 不硬判 door）：
    - 双线墙重复洞口 → 剔除（removed_doors 留痕）；
    - 距任何空间 >600mm 且无弧线 → 剔除（标注线/符号间隙）；
    - 有门扇弧线佐证 → door；结构缺口+平面图弧线双源互证 0.85，
      双图均有弧线 0.9，仅结构图弧线 0.8；
    - 有窗槛短档且宽度≥1200 且无弧线 → 移入 windows（判窗留痕）；
    - 其余保留为 opening（0.4–0.5），不冒充门；
    - 仅平面图有弧线、结构图无对应缺口（如主卧门）→ plan_only 门 0.6，
      需现场确认。
    """
    from core.pdf_plan_reader import (
        _nearest_room_distance, arc_matches_gap, rooms_near_gap)

    fusion = fused["fusion"]
    transform = (alignment["scale"], alignment["rotation_deg"],
                 *alignment["translation_mm"])
    rooms = fused.get("detected_rooms") or []

    # ---- 1) 证据准备：双图弧线统一到结构图坐标 ----
    s_arcs = [dict(a, from_plan="structure")
              for a in structure_plan.get("door_arcs") or []]
    f_arcs = []
    for arc in furnished_plan.get("door_arcs") or []:
        moved = {"from_plan": "furnished",
                 "radius_mm": round(arc["radius_mm"] * transform[0], 1),
                 "sweep_deg": arc.get("sweep_deg")}
        for key in ("hinge", "leaf_tip", "closed"):
            pt = arc.get(key)
            if pt:
                rx, ry = _rotate(pt, transform[1])
                moved[key] = (transform[0] * rx + transform[2],
                              transform[0] * ry + transform[3])
        f_arcs.append(moved)
    all_arcs = s_arcs + f_arcs

    s_details = structure_plan.get("door_details") or []
    tick_lookup = set()
    for det in s_details:
        if "jamb_ticks" in (det.get("evidence") or []):
            tick_lookup.add((round(det["start"][0]), round(det["start"][1]),
                             round(det["end"][0]), round(det["end"][1])))

    # ---- 2) 双线墙重复洞口去重 ----
    gaps = []
    for x1, y1, x2, y2 in structure_plan.get("doors") or []:
        if abs(y2 - y1) <= abs(x2 - x1):
            gaps.append({"axis": "H", "line": (y1 + y2) / 2,
                         "lo": min(x1, x2), "hi": max(x1, x2),
                         "seg": (x1, y1, x2, y2)})
        else:
            gaps.append({"axis": "V", "line": (x1 + x2) / 2,
                         "lo": min(y1, y2), "hi": max(y1, y2),
                         "seg": (x1, y1, x2, y2)})
    removed = []
    kept = []
    for gap in gaps:
        dup_of = None
        for other in kept:
            if other["axis"] != gap["axis"]:
                continue
            if abs(other["line"] - gap["line"]) > _DOOR_DUP_LINE_MM:
                continue
            overlap = min(other["hi"], gap["hi"]) - max(other["lo"], gap["lo"])
            shorter = min(other["hi"] - other["lo"], gap["hi"] - gap["lo"])
            if shorter > 0 and overlap / shorter >= _DOOR_DUP_OVERLAP:
                dup_of = other
                break
        if dup_of is not None:
            removed.append({
                "start": [round(gap["seg"][0], 1), round(gap["seg"][1], 1)],
                "end": [round(gap["seg"][2], 1), round(gap["seg"][3], 1)],
                "reason": "与保留洞口平行重复（线距 %dmm、跨度重叠≥%d%%）："
                          "双线墙两条面线各记一次洞口，剔除其一。"
                          % (round(abs(dup_of["line"] - gap["line"])),
                             round(_DOOR_DUP_OVERLAP * 100)),
            })
        else:
            kept.append(gap)

    # ---- 3) 弧线 → 最优缺口指派（一条弧只佐证一个缺口） ----
    from core.pdf_plan_reader import arc_gap_distance
    arc_best = {}  # arc_idx -> (distance, gap_idx)
    for ai, arc in enumerate(all_arcs):
        for gi, gap in enumerate(kept):
            x1, y1, x2, y2 = gap["seg"]
            if not arc_matches_gap(arc, x1, y1, x2, y2, tol=_DOOR_ARC_TOL_MM):
                continue
            dist = arc_gap_distance(arc, x1, y1, x2, y2)
            if ai not in arc_best or dist < arc_best[ai][0]:
                arc_best[ai] = (dist, gi)
    gap_arcs = {}
    for ai, (_dist, gi) in arc_best.items():
        gap_arcs.setdefault(gi, []).append(ai)

    # ---- 4) 逐缺口判定 ----
    doors_out = []       # 收敛后的门/开口（rich records）
    large_openings = []  # ≥2000mm 的开敞口：不是门，单列留痕
    windows_out = [tuple(w) for w in fused.get("windows") or []]
    matched_arc_ids = set()
    stats = {"structure_gaps": len(gaps), "duplicates": len(removed),
             "removed_noise": 0, "reclassified_window": 0,
             "door_dual": 0, "door_single": 0, "door_plan_only": 0,
             "opening": 0, "large_opening": 0}

    for gi, gap in enumerate(kept):
        x1, y1, x2, y2 = gap["seg"]
        width = gap["hi"] - gap["lo"]
        connects = rooms_near_gap(x1, y1, x2, y2, rooms)
        nearest = _nearest_room_distance(x1, y1, x2, y2, rooms)
        has_ticks = (round(x1), round(y1), round(x2), round(y2)) in tick_lookup

        arc_hits = gap_arcs.get(gi, [])

        base = {
            "start": [round(x1, 1), round(y1, 1)],
            "end": [round(x2, 1), round(y2, 1)],
            "width_mm": round(width, 1),
            "connects": connects,
        }

        if not arc_hits and nearest > _DOOR_FAR_MM:
            removed.append({
                "start": base["start"], "end": base["end"],
                "reason": "距任何空间边界 %dmm（>%dmm）且无门扇弧线佐证："
                          "判定为标注线/家具符号间隙，剔除。"
                          % (round(nearest), _DOOR_FAR_MM),
            })
            stats["removed_noise"] += 1
            continue

        if arc_hits:
            matched_arc_ids.update(arc_hits)
            # 铰链距离 ≤500mm 的弧线簇 = 同一扇门（结构图与平面图的同一门
            # 弧各一条，或同一门被描两次）；铰链分散的多条弧 = 结构图把相邻
            # 多门并成一个宽缺口——按弧簇拆回独立的门，位置/宽度以弧线为准，
            # 结构图缺口作墙体佐证。
            clusters = []
            for ai in arc_hits:
                hinge = all_arcs[ai].get("hinge")
                placed = False
                for cluster in clusters:
                    ref = all_arcs[cluster[0]].get("hinge")
                    if hinge and ref and math.hypot(
                            hinge[0] - ref[0], hinge[1] - ref[1]) <= 500.0:
                        cluster.append(ai)
                        placed = True
                        break
                if not placed:
                    clusters.append([ai])
            for cluster in clusters:
                sources = {all_arcs[ai]["from_plan"] for ai in cluster}
                both = sources == {"structure", "furnished"}
                dual = "furnished" in sources
                conf = 0.9 if both else (0.85 if dual else 0.8)
                # 位置取平面图弧线（设计师表达的门位最准），无则结构图弧线
                pick = next((ai for ai in cluster
                             if all_arcs[ai]["from_plan"] == "furnished"),
                            cluster[0])
                arc = all_arcs[pick]
                rec = dict(base)
                rec.update({
                    "type": "door",
                    "confidence": conf,
                    "source": "dual" if dual else "structure",
                    "evidence": ["wall_gap"] + sorted({
                        "door_arc_%s" % all_arcs[ai]["from_plan"]
                        for ai in cluster}),
                })
                if arc.get("hinge") and arc.get("closed"):
                    hx, hy = arc["hinge"]
                    cx, cy = arc["closed"]
                    rec["start"] = [round(hx, 1), round(hy, 1)]
                    rec["end"] = [round(cx, 1), round(cy, 1)]
                    rec["width_mm"] = round(arc.get("radius_mm") or width, 1)
                    rec["connects"] = rooms_near_gap(hx, hy, cx, cy, rooms) \
                        or connects
                    if len(clusters) > 1:
                        rec["note"] = ("结构图 %.0fmm 宽缺口由 %d 条门扇弧线佐证，"
                                       "按弧线拆回独立的门（位置/宽度以弧线为准）。"
                                       % (width, len(arc_hits)))
                if not rec["connects"]:
                    rec["note"] = (rec.get("note") or "") + \
                        "连通房间未能从闭环判定，需人工核对。"
                doors_out.append(rec)
                stats["door_dual" if dual else "door_single"] += 1
            continue

        if has_ticks and width >= _WINDOW_TICK_MIN_W_MM:
            windows_out.append((x1, y1, x2, y2))
            removed.append({
                "start": base["start"], "end": base["end"],
                "reason": "两端有窗槛短档、宽度 %.0fmm 且无门扇弧线佐证："
                          "由门洞清单改判为窗。" % width,
            })
            stats["reclassified_window"] += 1
            continue

        if not connects:
            removed.append({
                "start": base["start"], "end": base["end"],
                "reason": "不邻接任何已识别空间（最近边界 %dmm）且无门扇弧线佐证："
                          "疑似图面噪声洞口，剔除留痕。" % round(nearest),
            })
            stats["removed_noise"] += 1
            continue

        if width >= _LARGE_OPENING_MM:
            large_openings.append(dict(base, **{
                "type": "large_opening", "confidence": 0.4,
                "source": "structure",
                "evidence": ["wall_gap"] + (["jamb_ticks"] if has_ticks else []),
                "note": "宽度 %.0fmm 超过门洞量级：按开敞连通口/飘窗面单列，"
                        "不计入门集合。" % width,
            }))
            stats["large_opening"] += 1
            continue

        # 其余：有墙体缺口证据但无门扇佐证——诚实保留为 opening
        rec = dict(base)
        rec.update({
            "type": "opening",
            "confidence": 0.5 if width <= _DOOR_WIDTH_MAX_MM else 0.45,
            "source": "structure",
            "evidence": ["wall_gap"] + (["jamb_ticks"] if has_ticks else []),
        })
        doors_out.append(rec)
        stats["opening"] += 1

    # ---- 4) 仅平面图有弧线的门（结构图无对应缺口，如主卧门/室内分区门） ----
    for ai, arc in enumerate(f_arcs):
        global_idx = len(s_arcs) + ai
        if global_idx in matched_arc_ids:
            continue
        hinge = arc.get("hinge")
        closed = arc.get("closed")
        if not (hinge and closed):
            continue
        connects = rooms_near_gap(hinge[0], hinge[1], closed[0], closed[1],
                                  rooms, near=700.0)
        note = "仅平面布置图有门扇弧线、结构图无对应缺口：按 plan_only 纳入，需现场确认。"
        if not connects:
            # 铰链落在某空间内部（如马桶间这类复合空间内的分区门）：
            # 不是噪声，但也不能判定连通关系——如实标注。
            container = None
            for room in rooms:
                poly = _poly(room)
                if len(poly) >= 3 and _point_in_poly(hinge[0], hinge[1], poly):
                    container = room.get("name") or "未命名"
                    break
            if not container:
                continue  # 弧线不邻接也不属于任何空间：家具/符号残片，不采信
            connects = [container]
            note = ("仅平面布置图有门扇弧线，且位于“%s”内部（室内分区门，"
                    "结构图无隔墙/缺口）：按 plan_only 纳入，连通关系需现场确认。"
                    % container)
        doors_out.append({
            "type": "door",
            "start": [round(hinge[0], 1), round(hinge[1], 1)],
            "end": [round(closed[0], 1), round(closed[1], 1)],
            "width_mm": round(arc.get("radius_mm") or 0.0, 1),
            "connects": connects,
            "confidence": 0.6,
            "source": "plan_only",
            "evidence": ["door_arc_furnished"],
            "needs_site_verification": True,
            "note": note,
        })
        stats["door_plan_only"] += 1

    # ---- 5) 写回融合结果 ----
    fused["doors"] = [tuple(d["start"] + d["end"]) for d in doors_out]
    fused["windows"] = [(round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1))
                        for x1, y1, x2, y2 in windows_out]
    fused["door_count"] = len(fused["doors"])
    fused["window_count"] = len(fused["windows"])
    fused["door_details"] = doors_out
    fused["removed_doors"] = removed
    stats["converged_total"] = len(doors_out)
    stats["windows_total"] = len(fused["windows"])
    fusion["door_fusion"] = {
        "method": "结构图缺口 × 双图门扇弧线互证（弧线=内容流级门符号提取），"
                  "重复/噪声/判窗逐条留痕",
        "stats": stats,
        "doors": doors_out,
        "removed_doors": removed,
        "large_openings": large_openings,
    }
    fusion.setdefault("limitations_out", []).append(
        "门洞语义收敛：结构图 %d 个缺口 → %d 个保留（door %d、opening %d）"
        "+%d 个 plan_only 门；剔除 %d 个（双线重复 %d、标注噪声 %d）、"
        "改判为窗 %d 个、超宽开敞口单列 %d 个。仅门扇弧线佐证的判 door，"
        "其余如实标 opening。"
        % (stats["structure_gaps"],
           stats["door_dual"] + stats["door_single"] + stats["opening"],
           stats["door_dual"] + stats["door_single"], stats["opening"],
           stats["door_plan_only"],
           stats["duplicates"] + stats["removed_noise"],
           stats["duplicates"], stats["removed_noise"],
           stats["reclassified_window"], stats["large_opening"]))


def _label_structure_rooms(fused):
    """融合未执行/被拒绝：房间照常标注来源与置信度，不伪装成融合结果。"""
    base_conf = fused.get("confidence") or 0.6
    rooms = []
    for room in fused.get("detected_rooms") or []:
        room["source"] = "structure"
        room["confidence"] = round(_room_conf(base_conf, room), 2)
        rooms.append(room)
    fused["detected_rooms"] = rooms
    fused["fusion"]["stats"] = {"structure_rooms": len(rooms), "plan_rooms": 0,
                                "merged": 0, "consistent": 0,
                                "structure_only": len(rooms), "plan_only": 0,
                                "filtered": 0, "zone_subdivision": 0}


def _room_conf(base_conf, room):
    conf = base_conf
    if room.get("virtual_boundary"):
        conf = max(0.4, conf - _CONF_VIRTUAL_PENALTY)
    return conf


# ---------------------------------------------------------------- 几何基础

def _poly(room):
    return [(p["x"], p["y"]) for p in room.get("floor_points") or []]


def _centroid(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def _rotate(p, deg):
    x, y = p
    if deg == 90:
        return (-y, x)
    if deg == 180:
        return (-x, -y)
    if deg == 270:
        return (y, -x)
    return (x, y)


def _transform_rooms(rooms, transform):
    """按相似变换 (k, rot, tx, ty) 变换房间多边形/分区文字，返回拷贝。"""
    k, deg, tx, ty = transform
    moved = []
    for room in rooms:
        r = copy.deepcopy(room)
        r["floor_points"] = []
        for x, y in _poly(room):
            rx, ry = _rotate((x, y), deg)
            r["floor_points"].append({"x": k * rx + tx, "y": k * ry + ty})
        for zone in r.get("zones") or []:
            rx, ry = _rotate((zone["x"], zone["y"]), deg)
            zone["x"], zone["y"] = k * rx + tx, k * ry + ty
        if r.get("area_m2"):
            r["area_m2"] = round(r["area_m2"] * k * k, 2)
        moved.append(r)
    return moved


def _poly_area_m2(pts):
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2e6


def _poly_perimeter_m(pts):
    per = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        per += math.hypot(x2 - x1, y2 - y1)
    return per / 1000


def _point_in_poly(px, py, pts):
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < x_cross:
                inside = not inside
    return inside


def _rasterize(pts, x0, y0):
    """把多边形光栅化为 _CELL_MM 网格集合（格子中心在形内即计入）。"""
    min_i = int(math.floor((min(p[0] for p in pts) - x0) / _CELL_MM))
    max_i = int(math.floor((max(p[0] for p in pts) - x0) / _CELL_MM))
    min_j = int(math.floor((min(p[1] for p in pts) - y0) / _CELL_MM))
    max_j = int(math.floor((max(p[1] for p in pts) - y0) / _CELL_MM))
    cells = set()
    for i in range(min_i, max_i + 1):
        cx = x0 + (i + 0.5) * _CELL_MM
        for j in range(min_j, max_j + 1):
            if _point_in_poly(cx, y0 + (j + 0.5) * _CELL_MM, pts):
                cells.add((i, j))
    return cells


def _canonical(name):
    """房间名规范化：去掉自动编号尾缀（卧室2→卧室）。"""
    return re.sub(r"\d+$", "", (name or "").strip())


def _genuine(canonical_name):
    """是否真实房间名（排除未命名/纯数字闭环名）。"""
    if not canonical_name:
        return False
    if canonical_name.startswith("未命名"):
        return False
    if re.fullmatch(r"\d+", canonical_name):
        return False
    return True


def _room_name_set(room):
    """结构图房间的名字集合（含复合空间 zones 与 '+' 拆分，规范化后）。"""
    names = set()
    for part in (room.get("name") or "").split("+"):
        if _canonical(part):
            names.add(_canonical(part))
    for zone in room.get("zones") or []:
        if _canonical(zone.get("name")):
            names.add(_canonical(zone.get("name")))
    return names
