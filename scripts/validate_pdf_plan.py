"""Offline validation for vector-PDF floor plan parsing (M0 third input path).

验证项:
1. 自造矢量 PDF 上比例尺校准精度（pt→mm 误差 <1%）、房间闭环数量与面积
   （误差 <5%）、房间名关联、门窗洞口识别；
2. 显式 scale 参数路径；
3. 无任何标注的 PDF：比例尺未校准 → 低置信度 → 闸门不盲目放行 layout_draft；
4. 图片型（扫描）PDF 被明确拒绝，不伪造几何；
5. 端到端: mvp_pipeline 以 PDF 为空间输入跑通（demo 模式），布局草案放行
   并使用 PDF 几何。
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from scripts.generate_sample_pdf_plan import (  # noqa: E402
    GROUND_TRUTH,
    build_raster_sample,
    build_vector_sample,
)


def _sample_conditions(path):
    data = {
        "project": {
            "name": "PDF样例住宅",
            "house_type": "两室一厅住宅",
            "area_m2": 54,
            "design_type": "整屋自动化方案",
        },
        "family": {
            "residents": "3人",
            "composition": "夫妻+1孩",
            "work_from_home": "偶尔",
            "cooking_frequency": "每日",
            "storage_need": "高",
        },
        "style": {
            "primary_style": "现代简约",
            "keywords": "清爽 温暖 收纳",
            "color_tone": "白色、浅木色",
        },
        "budget": {"total_budget": 180000},
        "special_requirements": {
            "承重墙": "外墙及结构墙不可拆改，需保留",
            "上下水": "厨房与卫生间湿区位置不可移动",
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _check_vector_parsing(tmp):
    from core.pdf_plan_reader import read_pdf_plan

    pdf_path = os.path.join(tmp, "sample_vector.pdf")
    build_vector_sample(pdf_path)
    plan = read_pdf_plan(pdf_path)

    if not plan.get("accepted"):
        raise SystemExit("vector PDF was not accepted")
    pdf_meta = plan["pdf"]
    if not pdf_meta["dimensions_calibrated"]:
        raise SystemExit("scale should be calibrated from dimension/scale texts")
    truth = GROUND_TRUTH
    scale_err = abs(pdf_meta["pt_to_mm"] - truth["pt_to_mm"]) / truth["pt_to_mm"]
    if scale_err > 0.01:
        raise SystemExit(f"pt->mm factor error {scale_err:.4%} exceeds 1%")

    rooms = {room["name"]: room["area_m2"] for room in plan["detected_rooms"]}
    for name, area in truth["rooms"].items():
        if name not in rooms:
            raise SystemExit(f"room '{name}' not detected; got {sorted(rooms)}")
        err = abs(rooms[name] - area) / area
        if err > 0.05:
            raise SystemExit(f"room '{name}' area {rooms[name]} vs truth {area} (err {err:.2%})")
    if len(rooms) != len(truth["rooms"]):
        raise SystemExit(f"expected {len(truth['rooms'])} rooms, got {len(rooms)}: {rooms}")
    if plan["door_count"] != truth["door_count"]:
        raise SystemExit(f"expected {truth['door_count']} doors, got {plan['door_count']}")
    if plan["window_count"] != truth["window_count"]:
        raise SystemExit(f"expected {truth['window_count']} windows, got {plan['window_count']}")
    if plan["confidence"] < 0.6:
        raise SystemExit(f"calibrated plan confidence too low: {plan['confidence']}")

    # 显式比例参数路径（对无标注变体也应精确校准）
    nodim_path = os.path.join(tmp, "nodim.pdf")
    build_vector_sample(nodim_path, with_dimensions=False, with_scale_text=False)
    explicit = read_pdf_plan(nodim_path, scale="1:50")
    if explicit["pdf"]["scale_source"] != "explicit_param":
        raise SystemExit("explicit scale param not honored")
    if abs(explicit["pdf"]["pt_to_mm"] - truth["pt_to_mm"]) / truth["pt_to_mm"] > 0.01:
        raise SystemExit("explicit scale factor wrong")
    if len(explicit["detected_rooms"]) != len(truth["rooms"]):
        raise SystemExit("explicit scale path lost rooms")

    return plan, pdf_path


def _check_uncalibrated_gate(tmp):
    from core.automation_gate import build_automation_gate_package
    from core.needs_profile import build_needs_cognition_package
    from core.pdf_plan_reader import read_pdf_plan
    from core.space_profile import build_space_cognition_package

    nodim_path = os.path.join(tmp, "nodim_gate.pdf")
    build_vector_sample(nodim_path, with_dimensions=False, with_scale_text=False)
    plan = read_pdf_plan(nodim_path)
    if plan["pdf"]["dimensions_calibrated"]:
        raise SystemExit("no-annotation PDF should stay uncalibrated")
    if plan["confidence"] >= 0.5:
        raise SystemExit(f"uncalibrated plan confidence should be low, got {plan['confidence']}")

    conditions_path = os.path.join(tmp, "conditions_gate.json")
    _sample_conditions(conditions_path)
    with open(conditions_path, "r", encoding="utf-8") as f:
        conditions = json.load(f)
    out_dir = os.path.join(tmp, "gate_out")
    space_package = build_space_cognition_package(conditions, out_dir, cad_plan=plan)
    needs_package = build_needs_cognition_package(
        conditions, out_dir, space_profile=space_package["profile"])
    gate_package = build_automation_gate_package(
        space_package["profile"], needs_package["profile"], out_dir)

    geometry = space_package["profile"]["geometry"]
    if geometry["confidence"] >= 0.6:
        raise SystemExit("space profile should cap geometry confidence for uncalibrated PDF")
    if geometry["source_type"] != "pdf_vector":
        raise SystemExit(f"geometry source_type should be pdf_vector, got {geometry['source_type']}")
    if "layout_draft" in space_package["profile"]["readiness"]["ready_for"]:
        raise SystemExit("uncalibrated PDF must NOT be ready for layout_draft")
    blocked_modules = [item["module"] for item in gate_package["gate"]["blocked"]]
    if "layout_draft" not in blocked_modules:
        raise SystemExit("gate should block layout_draft for uncalibrated PDF geometry")
    return gate_package["gate"]


def _check_raster_rejection(tmp):
    from core.pdf_plan_reader import read_pdf_plan

    raster_path = os.path.join(tmp, "scanned.pdf")
    build_raster_sample(raster_path)
    plan = read_pdf_plan(raster_path)
    if plan.get("accepted"):
        raise SystemExit("raster PDF must not be accepted")
    if plan["source_type"] != "pdf_raster":
        raise SystemExit(f"raster PDF source_type wrong: {plan['source_type']}")
    if plan["walls"] or plan["detected_rooms"]:
        raise SystemExit("raster PDF must not fabricate geometry")
    message = "；".join(plan["limitations"])
    if "图片型" not in message or "CAD/DXF" not in message:
        raise SystemExit("raster rejection should explain the situation and alternatives")
    return plan


def _check_end_to_end(tmp, pdf_path):
    from core.ai_client import reset_client
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    conditions_path = os.path.join(tmp, "conditions_e2e.json")
    _sample_conditions(conditions_path)
    os.environ["AI_DEMO_MODE"] = "1"
    reset_client()
    result = run_mvp_concept_package(conditions_path, pdf_path=pdf_path)

    if "layout_draft" not in result.get("allowed_modules", []):
        raise SystemExit("pipeline should allow layout_draft with calibrated PDF input")
    with open(result["layout_json"], "r", encoding="utf-8") as f:
        layout = json.load(f)
    if layout.get("status") == "blocked_by_automation_gate":
        raise SystemExit("layout_draft unexpectedly blocked with calibrated PDF input")

    with open(result["space_profile"], "r", encoding="utf-8") as f:
        profile = json.load(f)
    if profile["geometry"]["source_type"] != "pdf_vector":
        raise SystemExit("space profile should mark pdf_vector as geometry source")
    room_names = {room.get("name") for room in profile["geometry"]["rooms"]}
    for name in GROUND_TRUTH["rooms"]:
        if name not in room_names:
            raise SystemExit(f"pipeline space profile lost PDF room '{name}': {room_names}")
    layout_text = json.dumps(layout, ensure_ascii=False)
    if not any(name in layout_text for name in GROUND_TRUTH["rooms"]):
        raise SystemExit("layout draft does not reference PDF-derived rooms")
    if not result.get("cad_plan") or not os.path.exists(result["cad_plan"]):
        raise SystemExit("pipeline did not persist the PDF-derived plan json")
    return result


def main():
    with tempfile.TemporaryDirectory() as tmp:
        plan, pdf_path = _check_vector_parsing(tmp)
        gate = _check_uncalibrated_gate(tmp)
        raster = _check_raster_rejection(tmp)
        result = _check_end_to_end(tmp, pdf_path)

        print(json.dumps({
            "ok": True,
            "scale": {
                "pt_to_mm": plan["pdf"]["pt_to_mm"],
                "truth": round(GROUND_TRUTH["pt_to_mm"], 6),
                "source": plan["pdf"]["scale_source"],
                "votes": plan["pdf"]["scale_votes"],
                "confidence": plan["pdf"]["scale_confidence"],
            },
            "rooms": {room["name"]: room["area_m2"] for room in plan["detected_rooms"]},
            "doors": plan["door_count"],
            "windows": plan["window_count"],
            "plan_confidence": plan["confidence"],
            "uncalibrated_gate_blocked": [item["module"] for item in gate["blocked"]],
            "raster_rejected_as": raster["source_type"],
            "e2e_allowed": result["allowed_modules"],
            "e2e_demo_mode": result["demo_mode"],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
