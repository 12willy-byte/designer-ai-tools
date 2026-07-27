# -*- coding: utf-8 -*-
"""设计师 AI 工具箱 Web 后端（Flask）。

职责：上传矢量 PDF 图纸 + 填写需求 → 异步跑 M0–M6 流水线 → 下载交付包 zip。

- POST /api/projects          multipart 上传（structure_pdf 必传 / furnished_pdf 可选 + 需求字段）
- GET  /api/jobs/<job_id>     任务状态与结果摘要
- GET  /api/jobs/<job_id>/download  交付包 zip 下载
- GET  /api/health            健康检查 + AI 模式

AI 模式：环境变量存在 DEEPSEEK_API_KEY / AI_API_KEY 时为真实模式，
否则强制 AI_DEMO_MODE=1 演示模式（离线占位输出，绝不冒充真实模型结果）。
"""
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
import zipfile

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ---- 路径与项目根 ----------------------------------------------------------
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SERVER_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

RUNS_ROOT = os.path.join(SERVER_DIR, "runs")
os.makedirs(RUNS_ROOT, exist_ok=True)

# ---- AI 模式判定（启动时一次确定，状态接口如实透出） ------------------------
AI_REAL_MODE = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("AI_API_KEY"))
if not AI_REAL_MODE:
    # 无 key 时强制演示模式：mock 输出带 demo 水印，不能被误当成真实模型结果。
    os.environ["AI_DEMO_MODE"] = "1"
AI_MODE_LABEL = "real" if AI_REAL_MODE else "demo"

MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB，整个请求体上限
ALLOWED_EXT = {".pdf"}

# 家庭情况下拉 → design_conditions.family.residents
FAMILY_PRESETS = {
    "single": "1人（单身）",
    "couple": "2人（夫妻）",
    "family3": "3人（夫妻+1孩）",
    "three_gen": "5人（三代同堂）",
    "rental": "出租房（租客未定）",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
CORS(app, origins=[
    "http://localhost:5273", "http://127.0.0.1:5273",
    "http://localhost:7100", "http://127.0.0.1:7100",
    "http://localhost:3000", "http://127.0.0.1:3000",
])

# job_id -> dict；内存态即可，进程重启任务丢失（README 已说明）
JOBS = {}
JOBS_LOCK = threading.Lock()


# ---- 工具函数 --------------------------------------------------------------
def _safe_pdf_name(filename, fallback):
    """净化上传文件名，只保留 .pdf，拒绝路径穿越。
    CJK 文件名经 secure_filename 会被剥光；即使残留 "pdf.pdf"
    （扩展名字母被误认为主体）也会造成两份上传互相覆盖。
    因此对「去扩展名后的主体」单独净化，为空就用 fallback 固定名
    （job 目录已隔离，固定名无碰撞风险）。"""
    stem_raw = os.path.splitext(filename or "")[0]
    stem = secure_filename(stem_raw).strip("._- ")
    if not stem:
        return fallback
    return stem[:80] + ".pdf"


def _is_pdf(file_storage):
    name = (file_storage.filename or "").lower()
    return os.path.splitext(name)[1] in ALLOWED_EXT


def _num_or_none(text):
    try:
        value = float(str(text).strip())
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def _split_special_requirements(text):
    """把自由文本特殊要求拆成带语义键的条目。
    core.space_profile._collect_constraints 按条目的「键」匹配约束关键词
    （承重/梁/柱/结构 → structural；水/电/燃气/烟道/管井 → mep），
    键没有命中关键词的文本会整体落入 unknowns，导致布局/预算被闸门拦截。
    因此这里按句切段并按内容归键，与 design_conditions 样例（承重墙/上下水键）对齐。"""
    entries = {}
    segments = [s.strip() for s in re.split(r"[；;\n。]+", text or "") if s.strip()]
    structural_n = mep_n = other_n = 0
    for seg in segments:
        if any(w in seg for w in ("承重", "梁", "柱", "结构", "不可拆", "不能拆")):
            structural_n += 1
            entries["承重结构%d" % structural_n] = seg
        elif any(w in seg for w in ("上下水", "水电", "燃气", "烟道", "管井", "湿区", "水位", "电位")):
            mep_n += 1
            entries["水电点位%d" % mep_n] = seg
        else:
            other_n += 1
            entries["其他要求%d" % other_n] = seg
    return entries


def _build_conditions(form):
    """把前端表单字段组装成 design_conditions（结构对齐
    templates/design_conditions.sample.json，由 core.design_schema 归一化）。"""
    project_name = (form.get("project_name") or "").strip() or "未命名项目"
    family_key = (form.get("family") or "").strip()
    residents = FAMILY_PRESETS.get(family_key, family_key or "")
    style = (form.get("style") or "").strip()
    color_tone = (form.get("color_tone") or "").strip()
    budget_wan = _num_or_none(form.get("budget_wan"))
    area_m2 = _num_or_none(form.get("area_m2"))
    special = (form.get("special_requirements") or "").strip()
    ceiling_mm = _num_or_none(form.get("ceiling_height_mm"))

    conditions = {
        "project": {
            "name": project_name,
            "design_type": "整屋概念提案",
            "source_note": "空间几何来自上传的矢量 PDF 图纸；家庭/风格/预算为业主补充条件",
        },
        "family": {"residents": residents} if residents else {},
        "style": {},
        "budget": {},
        "special_requirements": {},
    }
    if area_m2:
        # 建筑面积是预算估算（M5）闸门与单价档位判定的事实输入；
        # 图纸解析不保证能推出套内/建筑面积，因此由业主补充。
        conditions["project"]["area_m2"] = round(area_m2, 1)
    if style:
        conditions["style"]["primary_style"] = style
    if color_tone:
        conditions["style"]["color_tone"] = color_tone
    if budget_wan:
        conditions["budget"]["total_budget"] = int(round(budget_wan * 10000))
    if special:
        conditions["special_requirements"] = _split_special_requirements(special)
    if ceiling_mm:
        # 层高是 M5 预算工程量的事实依据；解析后逐房间注入（见 _run_job）。
        conditions["project"]["ceiling_height_mm"] = int(round(ceiling_mm))
    return conditions, ceiling_mm


def _parse_plans(structure_pdf, furnished_pdf, ceiling_mm):
    """预解析矢量 PDF（结构图为主、布置图为辅时做双图交叉验证融合），
    并把用户确认的层高注入每个识别房间。"""
    from core.pdf_plan_reader import read_pdf_plan

    plan = read_pdf_plan(structure_pdf)
    if not plan.get("accepted"):
        raise ValueError("图纸 PDF 无法作为空间输入：" +
                         "；".join(plan.get("limitations") or ["未知原因"]))
    if furnished_pdf:
        furnished = read_pdf_plan(furnished_pdf)
        if not furnished.get("accepted"):
            raise ValueError("平面布置图 PDF 无法作为空间输入：" +
                             "；".join(furnished.get("limitations") or ["未知原因"]))
        from core.plan_fusion import fuse_plans
        plan = fuse_plans(plan, furnished)
    if ceiling_mm:
        for room in plan.get("detected_rooms") or []:
            if isinstance(room, dict) and not room.get("ceiling_height_mm"):
                room["ceiling_height_mm"] = int(round(ceiling_mm))
    return plan


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _build_summary(result, run_dir, user_budget_wan):
    """从流水线返回与产物文件中提取结果页摘要。"""
    out_dir = result["output_dir"]
    from core.delivery_package import collect_assumptions

    profile = _read_json(result.get("space_profile") or "", {}) or {}
    rooms = ((profile.get("geometry") or {}).get("rooms")) or []
    room_names = [r.get("name") for r in rooms if r.get("name")]

    budget_low = budget_high = None
    budget_path = result.get("budget_estimate_json")
    if budget_path:
        estimate = _read_json(budget_path, {}) or {}
        totals = estimate.get("totals") or {}
        budget_low = totals.get("low")
        budget_high = totals.get("high")

    # 布局模式：降级布局（draft_degraded）必须在结果页如实透出——
    # 用户需要知道"为什么布局只是讨论稿"（降级原因逐条列出）。
    layout_mode = None
    degraded_reasons = []
    layout_doc = _read_json(result.get("layout_json") or "", {}) or {}
    if layout_doc.get("status") == "draft":
        layout_mode = layout_doc.get("layout_mode") or "draft"
        degraded_reasons = layout_doc.get("degraded_reasons") or []
    elif layout_doc.get("status"):
        layout_mode = layout_doc.get("status")

    questions = _read_json(result.get("unified_questions_to_confirm") or "", []) or []
    questions_out = [
        {
            "question": q.get("question", ""),
            "source": {"space": "空间解析", "needs": "需求画像"}.get(q.get("source"), q.get("source", "")),
            "category": q.get("category", ""),
            "reason": q.get("reason", ""),
            "required": bool(q.get("required")),
        }
        for q in questions if isinstance(q, dict) and q.get("question")
    ]

    assumptions = collect_assumptions(out_dir)

    gate = _read_json(result.get("automation_gate") or "", {}) or {}
    blocked = [
        {"module": item.get("module", ""), "reasons": item.get("reasons") or []}
        for item in (gate.get("blocked") or []) if isinstance(item, dict)
    ]

    delivery = result.get("delivery") or {}
    package_dir = delivery.get("package_dir")

    return {
        "mode": AI_MODE_LABEL,
        "demo_mode": bool(result.get("demo_mode")),
        "room_count": len(room_names),
        "room_names": room_names,
        "total_area_m2": (profile.get("geometry") or {}).get("total_area_m2"),
        "budget_low": budget_low,
        "budget_high": budget_high,
        "user_budget_wan": user_budget_wan,
        "layout_mode": layout_mode,
        "degraded_reasons": degraded_reasons,
        "allowed_modules": result.get("allowed_modules") or [],
        "blocked_modules": blocked,
        "questions": questions_out,
        "question_count": len(questions_out),
        "assumptions": assumptions,
        "assumption_count": len(assumptions),
        "delivery_file_count": delivery.get("file_count"),
        "delivery_package_dir": os.path.basename(package_dir) if package_dir else None,
        "fusion": result.get("plan_fusion"),
        "project_name": (profile.get("project") or {}).get("name"),
    }


def _zip_delivery(package_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(package_dir):
            for fname in files:
                full = os.path.join(root, fname)
                arc = os.path.relpath(full, os.path.dirname(package_dir))
                zf.write(full, arc)
    return zip_path


def _run_job(job_id, structure_pdf, furnished_pdf, conditions, ceiling_mm,
             user_budget_wan):
    """后台线程：解析 → 流水线 → 摘要 → 打 zip。"""
    run_dir = os.path.join(RUNS_ROOT, job_id)
    try:
        with JOBS_LOCK:
            JOBS[job_id]["status"] = "running"

        cad_plan = _parse_plans(structure_pdf, furnished_pdf, ceiling_mm)

        conditions_path = os.path.join(run_dir, "design_conditions.json")
        with open(conditions_path, "w", encoding="utf-8") as f:
            json.dump(conditions, f, ensure_ascii=False, indent=2)

        from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package
        result = run_mvp_concept_package(
            conditions_path,
            cad_plan=cad_plan,
            delivery_root=os.path.join(run_dir, "delivery"),
        )

        summary = _build_summary(result, run_dir, user_budget_wan)
        package_dir = (result.get("delivery") or {}).get("package_dir")
        zip_path = os.path.join(run_dir, "delivery_package.zip")
        _zip_delivery(package_dir, zip_path)

        with JOBS_LOCK:
            JOBS[job_id].update({
                "status": "done",
                "summary": summary,
                "zip_path": zip_path,
                "finished_at": time.time(),
            })
    except Exception as exc:  # noqa: BLE001 - 任务失败如实回报
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[job_id].update({
                "status": "failed",
                "error": str(exc),
                "finished_at": time.time(),
            })


# ---- 路由 ------------------------------------------------------------------
@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "ai_mode": AI_MODE_LABEL,
        "ai_mode_label": "真实 AI（DeepSeek）" if AI_REAL_MODE else "演示模式（离线占位输出）",
        "max_upload_mb": MAX_CONTENT_LENGTH // (1024 * 1024),
    })


@app.post("/api/projects")
def create_project():
    structure = request.files.get("structure_pdf")
    if structure is None or not structure.filename:
        return jsonify({"error": "请上传结构图 PDF（必传）"}), 400
    if not _is_pdf(structure):
        return jsonify({"error": "结构图只支持 PDF 文件（CAD 导出的矢量 PDF）"}), 400
    furnished = request.files.get("furnished_pdf")
    if furnished is not None and furnished.filename and not _is_pdf(furnished):
        return jsonify({"error": "布置图只支持 PDF 文件"}), 400
    if furnished is not None and not furnished.filename:
        furnished = None

    conditions, ceiling_mm = _build_conditions(request.form)
    budget_wan = _num_or_none(request.form.get("budget_wan"))

    job_id = uuid.uuid4().hex[:12]
    run_dir = os.path.join(RUNS_ROOT, job_id)
    os.makedirs(run_dir, exist_ok=False)

    structure_path = os.path.join(run_dir, _safe_pdf_name(structure.filename, "structure.pdf"))
    structure.save(structure_path)
    furnished_path = None
    if furnished is not None:
        furnished_path = os.path.join(run_dir, _safe_pdf_name(furnished.filename, "furnished.pdf"))
        furnished.save(furnished_path)

    with JOBS_LOCK:
        JOBS[job_id] = {
            "status": "queued",
            "mode": AI_MODE_LABEL,
            "created_at": time.time(),
            "run_dir": run_dir,
            "has_furnished": bool(furnished_path),
        }

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, structure_path, furnished_path, conditions, ceiling_mm, budget_wan),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "status": "queued", "mode": AI_MODE_LABEL})


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    if not re.fullmatch(r"[a-f0-9]{12}", job_id or ""):
        return jsonify({"error": "job_id 不合法"}), 400
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return jsonify({"error": "任务不存在（服务重启后历史任务不保留）"}), 404
        payload = {
            "job_id": job_id,
            "status": job["status"],
            "mode": job["mode"],
            "created_at": job["created_at"],
        }
        if job["status"] == "failed":
            payload["error"] = job.get("error", "未知错误")
        if job["status"] == "done":
            payload["summary"] = job.get("summary")
    return jsonify(payload)


@app.get("/api/jobs/<job_id>/download")
def job_download(job_id):
    if not re.fullmatch(r"[a-f0-9]{12}", job_id or ""):
        return jsonify({"error": "job_id 不合法"}), 400
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return jsonify({"error": "任务不存在"}), 404
        if job["status"] != "done":
            return jsonify({"error": "任务尚未完成，无法下载"}), 409
        zip_path = job.get("zip_path")
    if not zip_path or not os.path.exists(zip_path):
        return jsonify({"error": "交付包文件缺失"}), 404
    project = ((job.get("summary") or {}).get("project_name")) or "交付包"
    download_name = "%s_交付包.zip" % re.sub(r'[\\/:*?"<>|]', "_", project)
    return send_file(zip_path, as_attachment=True, download_name=download_name)


@app.errorhandler(413)
def too_large(_err):
    return jsonify({"error": "上传文件超过 50MB 上限"}), 413


if __name__ == "__main__":
    port = int(os.environ.get("FLASK_PORT", "8791"))
    # threaded=True：轮询状态接口不被长任务阻塞（流水线本身在独立线程）。
    app.run(host="127.0.0.1", port=port, threaded=True)
