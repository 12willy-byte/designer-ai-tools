#!/usr/bin/env python3
"""双图融合（结构图 + 平面布置图交叉验证合并）离线验收。

覆盖：
1. 真实样本融合（resources/real_samples/ 两份真实住宅矢量 PDF）：
   - 对齐质量指标合理（旋转/比例/平移/IoU）；
   - 主卧以 source=plan_only、低置信度、需现场确认并入；
   - 双源一致空间置信度提升（merged）；
   - 复合空间面积冲突如实记录并取结构图值；
   - 家具假环剔除、同名分区不重复计入；
   - 整体置信度只在有一致互证时小幅提升。
2. 旋转恢复：把结构图房间旋转 180°+缩放+平移构造"布置图"，融合应恢复
   旋转角并全部双源一致。
3. 诚实拒绝：镜像户型（锚点相对位置不一致、几何不重叠）必须拒绝融合，
   回退为只用结构图，且如实写 limitation。
4. 空布置图：无房间闭环时回退结构图单图结果。
5. demo 端到端：双 PDF 输入跑 M0→M6（AI_DEMO_MODE），布局草案覆盖主卧。

运行：AI_DEMO_MODE=1 python3 scripts/validate_plan_fusion.py
"""
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "resources", "real_samples")
STRUCTURE_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳原始图.pdf")
FURNISHED_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳平面.pdf")


def _fail(message):
    raise SystemExit("validate_plan_fusion FAILED: " + message)


def _load_samples():
    from core.pdf_plan_reader import read_pdf_plan
    if not (os.path.exists(STRUCTURE_PDF) and os.path.exists(FURNISHED_PDF)):
        _fail("真实样本缺失：resources/real_samples/")
    structure = read_pdf_plan(STRUCTURE_PDF)
    furnished = read_pdf_plan(FURNISHED_PDF)
    if not structure.get("accepted") or not furnished.get("accepted"):
        _fail("真实样本解析未被接受")
    return structure, furnished


def _check_real_fusion(structure, furnished):
    from core.plan_fusion import fuse_plans
    fused = fuse_plans(structure, furnished)
    alignment = fused["fusion"]["alignment"]
    stats = fused["fusion"]["stats"]

    if not alignment.get("accepted"):
        _fail("真实双图对齐被拒绝：%s" % alignment.get("reason"))
    if alignment["rotation_deg"] != 0:
        _fail("同一户型两份图纸不应需要旋转，got %s" % alignment["rotation_deg"])
    if not (0.95 <= alignment["scale"] <= 1.05):
        _fail("比例系数应在 1.0 附近（两图各自已校准），got %s" % alignment["scale"])
    if not (0.2 <= alignment["overall_iou"] <= 0.9):
        _fail("整体 IoU 不合理：%s" % alignment["overall_iou"])
    if alignment["best_pair_iou"] < 0.3:
        _fail("最佳匹配对 IoU 过低：%s" % alignment["best_pair_iou"])

    rooms = {r.get("name"): r for r in fused["detected_rooms"]}
    master = rooms.get("主卧")
    if not master:
        _fail("融合结果缺少主卧（平面图独有空间未并入）")
    if master.get("source") != "plan_only":
        _fail("主卧 source 应为 plan_only，got %s" % master.get("source"))
    if master.get("confidence", 1) >= 0.6:
        _fail("主卧置信度应低于双源空间，got %s" % master.get("confidence"))
    if not master.get("needs_site_verification"):
        _fail("主卧应标注需现场确认")

    merged = [r for r in fused["detected_rooms"] if r.get("source") == "merged"]
    if not merged:
        _fail("应有双源一致空间（source=merged）")
    for room in merged:
        base = 0.67 - (0.05 if room.get("virtual_boundary") else 0)
        if room.get("confidence", 0) <= base:
            _fail("双源一致空间 %s 置信度未提升：%s" % (room.get("name"), room.get("confidence")))

    conflicts = fused["fusion"]["conflicts"]
    if not any(c.get("type") == "area_mismatch" and "客厅" in c.get("room", "")
               for c in conflicts):
        _fail("复合空间两图面积口径差异应如实记入 conflicts")
    composite = rooms.get("客厅+餐厅+马桶间+厨房")
    if not composite or abs(composite.get("area_m2") - 63.14) > 0.5:
        _fail("复合空间冲突应取结构图值 63.14㎡")

    filtered = fused["fusion"]["filtered_furniture_rings"]
    # 家具假环剔除按端到端口径计数：读入层物理下限/浮动单线过滤
    # （removed_rooms）+ 融合层重叠分析剔除（filtered_furniture_rings）。
    # 读入层提前剔除后，融合层剔除数相应减少，合计口径不回退。
    reader_removed = len(structure.get("removed_rooms") or []) + \
        len(furnished.get("removed_rooms") or [])
    total_filtered = stats.get("filtered", 0) + reader_removed
    if total_filtered < 3 or stats.get("filtered", 0) + len(filtered) < 2:
        _fail("家具假环剔除数量不足：融合层 %s + 读入层 %s"
              % (stats.get("filtered"), reader_removed))
    # 最终房间清单不得含净宽 <1m 的假房间（物理下限）
    for room in fused["detected_rooms"]:
        pts = [(p["x"], p["y"]) for p in room.get("floor_points") or []]
        if len(pts) < 3:
            continue
        w = max(p[0] for p in pts) - min(p[0] for p in pts)
        h = max(p[1] for p in pts) - min(p[1] for p in pts)
        if min(w, h) < 1000.0:
            _fail("融合结果含净宽 <1m 的假房间：%s（%.0fx%.0f）"
                  % (room.get("name"), w, h))
    if not fused["fusion"]["zone_subdivisions"]:
        _fail("平面图厨房应识别为复合空间同名分区（zone_subdivision）")

    if stats.get("plan_only") != 1:
        _fail("plan_only 空间应恰好 1 个（主卧），got %s" % stats.get("plan_only"))
    if not (structure["confidence"] < fused["confidence"] <= 0.75):
        _fail("整体置信度应小幅提升，%s -> %s" % (structure["confidence"], fused["confidence"]))

    lim = "；".join(fused.get("limitations") or [])
    for keyword in ("plan_only", "现场确认", "IoU"):
        if keyword not in lim:
            _fail("limitations 缺少 '%s' 说明" % keyword)
    return fused


def _check_rotation_recovery(structure):
    """把结构图房间旋转 180°+缩放 1.02+平移构造布置图，应恢复旋转并全一致。"""
    from core.plan_fusion import fuse_plans
    fake = copy.deepcopy(structure)
    fake["source"] = "synthetic_rot180"
    k, tx, ty = 1.02, 5000.0, -3000.0
    for room in fake["detected_rooms"]:
        for p in room.get("floor_points") or []:
            x, y = p["x"], p["y"]
            p["x"], p["y"] = -x * k + tx, -y * k + ty
        for zone in room.get("zones") or []:
            x, y = zone["x"], zone["y"]
            zone["x"], zone["y"] = -x * k + tx, -y * k + ty
        if room.get("area_m2"):
            room["area_m2"] = round(room["area_m2"] * k * k, 2)
    fused = fuse_plans(structure, fake)
    alignment = fused["fusion"]["alignment"]
    if not alignment.get("accepted"):
        _fail("旋转 180° 的合成布置图对齐被拒绝：%s" % alignment.get("reason"))
    if alignment["rotation_deg"] != 180:
        _fail("应恢复旋转 180°，got %s" % alignment["rotation_deg"])
    if alignment["overall_iou"] < 0.7:
        _fail("旋转恢复后整体 IoU 应接近 1，got %s" % alignment["overall_iou"])
    stats = fused["fusion"]["stats"]
    if stats["consistent"] < len(structure["detected_rooms"]) - 1:
        _fail("合成双图应几乎全部双源一致，got %s" % stats["consistent"])
    return fused


def _check_honest_rejection(structure):
    """另一套户型（同名空间但相对位置完全不同）：几何不可能对齐，
    必须拒绝融合、回退结构图并如实说明——不退化为乱合并。"""
    from core.plan_fusion import fuse_plans

    def square(cx, cy, half):
        return [{"x": cx - half, "y": cy - half}, {"x": cx + half, "y": cy - half},
                {"x": cx + half, "y": cy + half}, {"x": cx - half, "y": cy + half}]

    rooms = []
    # 同名锚点（客厅/餐厅/厨房）放在与结构图完全不同的相对位置上
    for name, cx, cy, half in [("客厅", 0, 0, 2200), ("餐厅", 30000, 0, 1600),
                               ("厨房", 0, 30000, 1500), ("主卧", 30000, 30000, 2100),
                               ("卧室", 15000, 15000, 1800)]:
        area = round((2 * half) ** 2 / 1e6, 2)
        rooms.append({"name": name, "floor_points": square(cx, cy, half),
                      "area_m2": area, "perimeter_m": round(8 * half / 1000, 2)})
    fake = {
        "source": "synthetic_other_apartment",
        "detected_rooms": rooms,
        "limitations": [],
        "confidence": 0.7,
        "pdf": {"pt_to_mm": 7.2, "dimensions_calibrated": True},
    }
    fused = fuse_plans(structure, fake)
    alignment = fused["fusion"]["alignment"]
    if alignment.get("accepted"):
        _fail("不同户型必须拒绝融合（IoU=%s）" % alignment.get("overall_iou"))
    rooms_out = fused.get("detected_rooms") or []
    if len(rooms_out) != len(structure["detected_rooms"]):
        _fail("拒绝融合后应保持结构图房间清单不变")
    if any(r.get("source") == "plan_only" for r in rooms_out):
        _fail("拒绝融合后不得并入任何 plan_only 空间")
    if "拒绝" not in "；".join(fused.get("limitations") or []):
        _fail("拒绝融合必须在 limitations 中如实说明")
    return fused


def _check_empty_furnished(structure):
    from core.plan_fusion import fuse_plans
    empty = {"source": "empty", "detected_rooms": [], "limitations": []}
    fused = fuse_plans(structure, empty)
    if fused["fusion"]["alignment"].get("accepted"):
        _fail("空布置图不应通过对齐")
    if len(fused.get("detected_rooms") or []) != len(structure["detected_rooms"]):
        _fail("空布置图融合应回退为结构图房间清单")
    return fused


def _check_end_to_end(tmp):
    from core.ai_client import reset_client
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    conditions = {
        "project": {"name": "双图融合验收", "house_type": "三室两厅住宅",
                    "area_m2": 110, "design_type": "整屋自动化方案"},
        "family": {"residents": "4人", "composition": "夫妻+2孩",
                   "cooking_frequency": "每日", "storage_need": "高"},
        "style": {"primary_style": "现代简约", "keywords": "清爽 温暖",
                  "color_tone": "白色、浅木色"},
        "budget": {"total_budget": 350000},
        "special_requirements": {"承重墙": "外墙及结构墙不可拆改，需保留",
                                 "上下水": "厨房与卫生间湿区位置不可移动"},
    }
    conditions_path = os.path.join(tmp, "conditions_fusion.json")
    with open(conditions_path, "w", encoding="utf-8") as f:
        json.dump(conditions, f, ensure_ascii=False, indent=2)

    os.environ["AI_DEMO_MODE"] = "1"
    reset_client()
    result = run_mvp_concept_package(
        conditions_path,
        pdf_path=STRUCTURE_PDF,
        pdf_furnished_path=FURNISHED_PDF,
    )
    if not result.get("plan_fusion"):
        _fail("端到端结果缺少 plan_fusion 块")
    if "layout_draft" not in result.get("allowed_modules", []):
        _fail("双图输入应放行 layout_draft")
    with open(result["layout_json"], "r", encoding="utf-8") as f:
        layout_text = f.read()
    if "主卧" not in layout_text:
        _fail("双图融合后布局草案应覆盖主卧")
    with open(result["space_profile"], "r", encoding="utf-8") as f:
        profile = json.load(f)
    if profile["geometry"]["source_type"] != "pdf_fusion":
        _fail("空间画像 source_type 应为 pdf_fusion，got %s"
              % profile["geometry"]["source_type"])
    master = [r for r in profile["geometry"]["rooms"] if r.get("name") == "主卧"]
    if not master or master[0].get("source") != "plan_only":
        _fail("空间画像中的主卧应带 source=plan_only")
    if not master[0].get("needs_site_verification"):
        _fail("空间画像中的主卧应标注需现场确认")
    if not result.get("delivery"):
        _fail("交付包未生成")
    return result


def main():
    structure, furnished = _load_samples()
    fused = _check_real_fusion(structure, furnished)
    _check_rotation_recovery(structure)
    _check_honest_rejection(structure)
    _check_empty_furnished(structure)
    with tempfile.TemporaryDirectory() as tmp:
        result = _check_end_to_end(tmp)
        with open(result["layout_json"], encoding="utf-8") as f:
            master_in_layout = "主卧" in f.read()

    alignment = fused["fusion"]["alignment"]
    print(json.dumps({
        "ok": True,
        "alignment": {
            "accepted": alignment["accepted"],
            "rotation_deg": alignment["rotation_deg"],
            "scale": alignment["scale"],
            "translation_mm": alignment["translation_mm"],
            "overall_iou": alignment["overall_iou"],
            "best_pair_iou": alignment["best_pair_iou"],
        },
        "stats": fused["fusion"]["stats"],
        "confidence": {"structure": structure["confidence"], "fused": fused["confidence"]},
        "rooms": {r["name"]: {"area_m2": r.get("area_m2"), "source": r.get("source"),
                              "confidence": r.get("confidence")}
                  for r in fused["detected_rooms"]},
        "conflicts": len(fused["fusion"]["conflicts"]),
        "filtered_furniture_rings": len(fused["fusion"]["filtered_furniture_rings"]),
        "rotation_recovery_180": True,
        "other_apartment_rejected": True,
        "e2e_master_bedroom_in_layout": master_in_layout,
        "e2e_allowed": result["allowed_modules"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
