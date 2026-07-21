#!/usr/bin/env python3
"""门语义跨图融合（第四阶段）离线验收。

覆盖：
1. 真实样本双图融合后的门集合收敛：
   - 门总数（door + opening）收敛到 [8, 15]（修正前结构图缺口 37 个）；
   - 每条 door/opening 记录有 type/start/end/confidence/source，opening 至少
     连通 1 个房间（door 允许以 note 说明连通待核）；
   - removed_doors 非空且每条有 reason（剔除留痕）；
   - 置信度分级：dual 门（≥0.85）> plan_only（0.6）> opening（≤0.5）；
   - 入户门存在且双源互证（evidence 含 door_arc_structure 与
     door_arc_furnished，confidence 0.9）；
   - 窗识别改进：融合后 windows ≥ 5（修正前单图仅 1 个）。
2. 单图路径零退化：结构图单读 door_count 仍为 37（未启用融合）、
   door_details/door_arcs/jamb_tick_gaps 均存在；平面图能提取 7 条门扇弧线。
3. 合成样本回归：generate_sample_pdf_plan 生成的矢量 PDF 解析不报错，
   门窗计数与基准一致。

运行：AI_DEMO_MODE=1 python3 scripts/validate_door_fusion.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLE_DIR = os.path.join(ROOT, "resources", "real_samples")
STRUCTURE_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳原始图.pdf")
FURNISHED_PDF = os.path.join(SAMPLE_DIR, "罗菁深圳平面.pdf")


def _fail(message):
    raise SystemExit("validate_door_fusion FAILED: " + message)


def _load_samples():
    from core.pdf_plan_reader import read_pdf_plan
    if not (os.path.exists(STRUCTURE_PDF) and os.path.exists(FURNISHED_PDF)):
        _fail("真实样本缺失：resources/real_samples/")
    structure = read_pdf_plan(STRUCTURE_PDF)
    furnished = read_pdf_plan(FURNISHED_PDF)
    if not structure.get("accepted") or not furnished.get("accepted"):
        _fail("真实样本解析未被接受")
    return structure, furnished


def _check_single_image_no_regression(structure, furnished):
    """单图路径：不启用融合时行为与第三阶段一致，新增字段就位。"""
    if structure.get("door_count") != 37:
        _fail("结构图单图 door_count 应保持 37（零退化），got %s"
              % structure.get("door_count"))
    if structure.get("window_count") != 1:
        _fail("结构图单图 window_count 应保持 1（零退化），got %s"
              % structure.get("window_count"))
    if not structure.get("door_details"):
        _fail("结构图单图应输出 door_details（单图语义分级）")
    for det in structure["door_details"]:
        for key in ("type", "start", "end", "confidence", "source", "evidence"):
            if key not in det:
                _fail("单图 door_details 记录缺少字段 %s" % key)
    if not structure.get("door_arcs"):
        _fail("结构图应提取到门扇弧线（入户门），got 空")
    if not structure.get("jamb_tick_gaps"):
        _fail("结构图应识别窗槛短档标记（jamb_tick_gaps），got 空")
    arcs = furnished.get("door_arcs") or []
    if len(arcs) != 7:
        _fail("平面图应提取 7 条门扇弧线（圆桌假弧已剔除），got %d" % len(arcs))
    for arc in arcs:
        for key in ("hinge", "leaf_tip", "closed", "radius_mm"):
            if key not in arc:
                _fail("弧线记录缺少字段 %s" % key)


def _check_door_fusion(structure, furnished):
    from core.plan_fusion import fuse_plans
    fused = fuse_plans(structure, furnished)
    door_fusion = (fused.get("fusion") or {}).get("door_fusion")
    if not door_fusion:
        _fail("融合结果缺少 fusion.door_fusion 块")
    stats = door_fusion["stats"]
    doors = door_fusion["doors"]
    removed = door_fusion["removed_doors"]

    # 1) 收敛目标：37 缺口 → [8, 15]
    total = stats.get("converged_total", len(doors))
    if not (8 <= total <= 15):
        _fail("收敛后门总数应在 [8, 15]，got %d" % total)
    if stats.get("structure_gaps") != 37:
        _fail("结构图缺口基数应为 37，got %s" % stats.get("structure_gaps"))

    # 2) 记录完整性
    for rec in doors:
        for key in ("type", "start", "end", "confidence", "source"):
            if key not in rec:
                _fail("门记录缺少字段 %s：%s" % (key, rec))
        if rec["type"] not in ("door", "opening"):
            _fail("未知门记录类型：%s" % rec["type"])
        if rec["type"] == "opening" and not rec.get("connects"):
            _fail("opening 至少应连通 1 个房间：%s" % rec)
        if rec["type"] == "door" and not rec.get("connects") \
                and not rec.get("note"):
            _fail("door 连通为空时必须以 note 说明：%s" % rec)

    # 3) 剔除留痕
    if not removed:
        _fail("removed_doors 应非空（剔除留痕）")
    for rec in removed:
        if not rec.get("reason"):
            _fail("removed_doors 记录缺少 reason：%s" % rec)
    if stats.get("duplicates", 0) < 1 or stats.get("removed_noise", 0) < 1:
        _fail("应同时存在重复剔除与噪声剔除两类留痕：%s" % stats)

    # 4) 置信度分级：dual ≥0.85 > plan_only 0.6 > opening ≤0.5
    dual = [d for d in doors if d["type"] == "door" and d["source"] == "dual"]
    plan_only = [d for d in doors if d["source"] == "plan_only"]
    openings = [d for d in doors if d["type"] == "opening"]
    if not dual:
        _fail("应有双源互证的 door（弧线+结构缺口）")
    for d in dual:
        if d["confidence"] < 0.85:
            _fail("dual 门置信度应 ≥0.85：%s" % d)
    for d in plan_only:
        if d["confidence"] != 0.6 or not d.get("needs_site_verification"):
            _fail("plan_only 门应为 0.6 且标注需现场确认：%s" % d)
    for d in openings:
        if d["confidence"] > 0.5:
            _fail("opening 置信度应 ≤0.5（诚实降级）：%s" % d)

    # 5) 入户门：双源互证、0.9
    entrance = [d for d in doors
                if {"door_arc_structure", "door_arc_furnished"}
                <= set(d.get("evidence") or [])]
    if not entrance:
        _fail("入户门应同时有双图弧线佐证（door_arc_structure + "
              "door_arc_furnished）")
    if not any(abs(d["confidence"] - 0.9) < 1e-9 for d in entrance):
        _fail("双图弧线互证的门置信度应为 0.9：%s" % entrance)

    # 6) 窗识别改进：1 → ≥5
    if fused.get("window_count", 0) < 5:
        _fail("融合后窗数量应 ≥5（窗槛短档改判），got %s"
              % fused.get("window_count"))
    if stats.get("reclassified_window", 0) < 1:
        _fail("应有洞口经窗槛短档改判为窗（reclassified_window）")

    # 7) 计数一致性
    if fused.get("door_count") != len(doors):
        _fail("fused door_count 与 door_details 不一致")
    return fused


def _check_synthetic_regression():
    """合成两室一厅样本：解析不报错，门窗计数与基准一致。"""
    from scripts.generate_sample_pdf_plan import GROUND_TRUTH, build_vector_sample
    from core.pdf_plan_reader import read_pdf_plan
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = os.path.join(tmp, "sample_vector.pdf")
        build_vector_sample(pdf_path)
        plan = read_pdf_plan(pdf_path)
    if not plan.get("accepted"):
        _fail("合成样本解析未被接受")
    if plan.get("door_count") != GROUND_TRUTH["door_count"]:
        _fail("合成样本门数 %s ≠ 基准 %s"
              % (plan.get("door_count"), GROUND_TRUTH["door_count"]))
    if plan.get("window_count") != GROUND_TRUTH["window_count"]:
        _fail("合成样本窗数 %s ≠ 基准 %s"
              % (plan.get("window_count"), GROUND_TRUTH["window_count"]))
    return plan


def main():
    structure, furnished = _load_samples()
    _check_single_image_no_regression(structure, furnished)
    fused = _check_door_fusion(structure, furnished)
    _check_synthetic_regression()

    stats = fused["fusion"]["door_fusion"]["stats"]
    print(json.dumps({
        "ok": True,
        "door_fusion_stats": stats,
        "door_count": fused["door_count"],
        "window_count": fused["window_count"],
        "removed_doors": len(fused["removed_doors"]),
        "single_image": {
            "structure_door_count": structure["door_count"],
            "structure_arcs": len(structure.get("door_arcs") or []),
            "structure_tick_gaps": len(structure.get("jamb_tick_gaps") or []),
            "furnished_arcs": len(furnished.get("door_arcs") or []),
        },
        "synthetic_sample_ok": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
