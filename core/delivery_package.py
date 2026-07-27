"""M6 delivery package assembly.

Collects the scattered artifacts produced by M0-M5 (concept_output/) into one
deliverable directory for the designer / small studio:

    delivery/<项目名>_<时间戳>/
      01_业主版/           概念 PPTX + 意向板 PNG（给业主看）
      02_设计师工作版/     布局草案、预算 Excel（新增）、M3/M4/M5 工作 JSON
      03_事实与假设/       M0/M1/M2 全套 JSON、待确认问题、汇总假设清单
      manifest.json        交付清单（每个文件的来源模块/生成时间/schema/生成模式 + 闸门状态）
      交付说明.md          人类可读总览（拦截说明 + 校准提示 + 下一步建议）

Core principle — full traceability:
- every file in manifest.json traces back to the module and source artifact
  that produced it (source path, mtime, schema_version, generation mode);
- modules blocked by the M2 automation gate never get fabricated empty files;
  they are recorded in manifest.blocked_modules and 交付说明.md with reasons.

The only newly generated artifact in M6 is the budget workbook (openpyxl):
all numbers are copied verbatim from budget_estimate.json / material_list.json
(rule-engine output) — M6 never recomputes or modifies a number.
"""
import json
import os
import re
import shutil
from datetime import datetime

from core.ai_client import get_client

SCHEMA_VERSION = "delivery_manifest.v1"

OWNER_DIR = "01_业主版"
DESIGNER_DIR = "02_设计师工作版"
FACTS_DIR = "03_事实与假设"

AUDIENCE_LABELS = {
    "owner": "业主",
    "designer": "设计师",
    "facts": "事实与假设（双方复核用）",
    "package": "交付包自身",
}

MODULE_LABELS = {
    "M0": "M0 空间对象建档",
    "M1": "M1 需求解析",
    "M2": "M2 约束检查/自动化闸门",
    "M3": "M3 概念方案",
    "M4": "M4 布局草案",
    "M5": "M5 预算与材料清单",
    "M6": "M6 交付打包",
}

GATE_MODULE_LABELS = {
    "concept_package": "概念提案包",
    "layout_draft": "布局草案",
    "budget_estimate": "预算估算",
    "material_palette": "材料/色彩建议",
    "construction_docs": "施工级图纸/文档",
}

# (源文件名, 目标相对路径, audience, 来源模块, 是否必含)
_COPY_PLAN = [
    # 01 业主版
    ("概念方案.pptx", OWNER_DIR + "/概念方案.pptx", "owner", "M3", True),
    ("风格意向板.png", OWNER_DIR + "/风格意向板.png", "owner", "M3", False),
    ("色彩方案.png", OWNER_DIR + "/色彩方案.png", "owner", "M3", False),
    ("材质方案.png", OWNER_DIR + "/材质方案.png", "owner", "M3", False),
    # 02 设计师工作版
    ("设计定位.txt", DESIGNER_DIR + "/设计定位.txt", "designer", "M3", False),
    ("设计定位.json", DESIGNER_DIR + "/设计定位.json", "designer", "M3", False),
    ("色彩方案色板.json", DESIGNER_DIR + "/色彩方案色板.json", "designer", "M3", False),
    ("材质方案.json", DESIGNER_DIR + "/材质方案.json", "designer", "M3", False),
    ("layout_draft.json", DESIGNER_DIR + "/layout_draft.json", "designer", "M4", False),
    ("layout_draft_summary.md", DESIGNER_DIR + "/layout_draft_summary.md", "designer", "M4", False),
    ("budget_estimate.json", DESIGNER_DIR + "/budget_estimate.json", "designer", "M5", False),
    ("material_list.json", DESIGNER_DIR + "/material_list.json", "designer", "M5", False),
    ("budget_summary.md", DESIGNER_DIR + "/budget_summary.md", "designer", "M5", False),
    # 03 事实与假设
    ("space_profile.json", FACTS_DIR + "/space_profile.json", "facts", "M0", True),
    ("scan_summary.json", FACTS_DIR + "/scan_summary.json", "facts", "M0", False),
    ("cad_plan.json", FACTS_DIR + "/cad_plan.json", "facts", "M0", False),
    ("space_observations.json", FACTS_DIR + "/space_observations.json", "facts", "M0", False),
    ("questions_to_confirm.json", FACTS_DIR + "/questions_to_confirm.json", "facts", "M0", False),
    ("needs_profile.json", FACTS_DIR + "/needs_profile.json", "facts", "M1", True),
    ("needs_observations.json", FACTS_DIR + "/needs_observations.json", "facts", "M1", False),
    ("needs_questions_to_confirm.json", FACTS_DIR + "/needs_questions_to_confirm.json", "facts", "M1", False),
    ("automation_gate.json", FACTS_DIR + "/automation_gate.json", "facts", "M2", True),
    ("constraint_report.json", FACTS_DIR + "/constraint_report.json", "facts", "M2", False),
    ("unified_questions_to_confirm.json", FACTS_DIR + "/unified_questions_to_confirm.json", "facts", "M2", False),
    # AI 输出防御留痕：chat_json 契约层的修复/降级事件（无事件时 event_count=0）。
    ("ai_repair_log.json", FACTS_DIR + "/ai_repair_log.json", "facts", "M3-M5", False),
]

# 被闸门拦截的模块 -> 其产物文件名（用于确认包内没有伪造文件）
_BLOCKED_ARTIFACTS = {
    "layout_draft": ["layout_draft.json", "layout_draft_summary.md"],
    "budget_estimate": ["budget_estimate.json", "material_list.json",
                        "budget_summary.md", "预算方案.xlsx"],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_delivery_package(source_dir, gate=None, pptx_path=None,
                           delivery_root=None, project_name=None,
                           package_name=None, demo_mode=None, provider=None):
    """Assemble the M6 delivery package from a concept_output directory.

    ``source_dir`` is the concept_output directory holding M0-M5 artifacts.
    ``pptx_path`` overrides the PPTX location when the pipeline wrote it
    outside source_dir. Returns a dict with package_dir / manifest_path /
    readme_path / workbook_path (None when budget was blocked).
    """
    if delivery_root is None:
        delivery_root = os.path.join(os.path.dirname(os.path.abspath(source_dir)), "delivery")
    os.makedirs(delivery_root, exist_ok=True)

    client = get_client()
    if demo_mode is None:
        demo_mode = bool(client.demo_mode)
    if provider is None:
        provider = client.provider
    generation_mode = "demo" if demo_mode else "real_ai"

    if not project_name:
        project_name = _read_project_name(source_dir) or "未命名项目"
    if not package_name:
        package_name = "%s_%s" % (_sanitize_name(project_name),
                                  datetime.now().strftime("%Y%m%d_%H%M%S"))
    package_dir = os.path.join(delivery_root, package_name)
    for sub in (OWNER_DIR, DESIGNER_DIR, FACTS_DIR):
        os.makedirs(os.path.join(package_dir, sub), exist_ok=True)

    gate = gate or _read_json(os.path.join(source_dir, "automation_gate.json")) or {}
    blocked = gate.get("blocked") or []
    blocked_names = {item.get("module") for item in blocked}

    # --- 1. copy artifacts -------------------------------------------------
    files = []
    skipped_missing = []
    for src_name, rel_dest, audience, module, required in _COPY_PLAN:
        src = os.path.join(source_dir, src_name)
        if src_name == "概念方案.pptx" and pptx_path:
            src = pptx_path
        if not os.path.exists(src):
            if required:
                raise FileNotFoundError("必含产物缺失：%s" % src)
            skipped_missing.append(src_name)
            continue
        dest = os.path.join(package_dir, rel_dest)
        shutil.copy2(src, dest)
        files.append(_manifest_entry(src, rel_dest, audience, module, generation_mode, provider))

    # --- 2. budget workbook (the only newly generated artifact) ------------
    workbook_path = None
    estimate = _read_json(os.path.join(source_dir, "budget_estimate.json"))
    material_list = _read_json(os.path.join(source_dir, "material_list.json"))
    if estimate and estimate.get("status") == "estimate" and "budget_estimate" not in blocked_names:
        workbook_path = os.path.join(package_dir, DESIGNER_DIR, "预算方案.xlsx")
        build_budget_workbook(estimate, material_list, workbook_path)
        entry = _manifest_entry(
            os.path.join(source_dir, "budget_estimate.json"),
            DESIGNER_DIR + "/预算方案.xlsx", "designer", "M5+M6",
            generation_mode, provider,
            note="数字逐字复制自 budget_estimate.json / material_list.json，M6 不重算",
        )
        entry["schema_version"] = None
        entry["generated_at"] = datetime.fromtimestamp(
            os.path.getmtime(workbook_path)).isoformat(timespec="seconds")
        files.append(entry)

    # --- 3. assumptions index ----------------------------------------------
    assumptions = collect_assumptions(source_dir)
    assumptions_path = os.path.join(package_dir, FACTS_DIR, "assumptions_index.md")
    with open(assumptions_path, "w", encoding="utf-8") as f:
        f.write(render_assumptions_index(assumptions, project_name))
    files.append(_manifest_entry(
        assumptions_path, FACTS_DIR + "/assumptions_index.md", "facts", "M6",
        generation_mode, provider,
        note="M3/M4/M5 各产物 assumptions 去重汇总",
    ))

    # --- 4. manifest ---------------------------------------------------------
    blocked_entries = []
    for item in blocked:
        module = item.get("module")
        blocked_entries.append({
            "module": module,
            "label": item.get("label") or GATE_MODULE_LABELS.get(module, module),
            "reasons": item.get("reasons") or [],
            "expected_artifacts": _BLOCKED_ARTIFACTS.get(module, []),
            "files_included": [],
            "note": "该模块被 M2 自动化闸门拦截，交付包不伪造其产物。",
        })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "package": {
            "name": package_name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "project_name": project_name,
        },
        "generation": {
            "mode": generation_mode,
            "provider": provider,
        },
        "gate": {
            "allowed": gate.get("allowed") or [],
            "blocked": blocked_entries,
            "warnings": gate.get("warnings") or [],
        },
        "files": files,
        "skipped_missing_sources": skipped_missing,
    }
    manifest_path = os.path.join(package_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # --- 5. human-readable readme -------------------------------------------
    readme_path = os.path.join(package_dir, "交付说明.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(render_delivery_readme(manifest, assumptions, estimate, material_list,
                                       project_name))

    return {
        "package_dir": package_dir,
        "manifest": manifest_path,
        "readme": readme_path,
        "assumptions_index": assumptions_path,
        "budget_workbook": workbook_path,
        "file_count": len(files),
        "blocked_modules": [e["module"] for e in blocked_entries],
    }


def collect_assumptions(source_dir):
    """Collect assumptions from M3/M4/M5 artifacts, deduped, with sources.

    Returns a list of {"text": ..., "sources": [...]} sorted by first source.
    """
    found = {}

    def _add(text, source):
        text = str(text or "").strip()
        if not text:
            return
        if not text.startswith("假设："):
            text = "假设：" + text
        found.setdefault(text, [])
        if source not in found[text]:
            found[text].append(source)

    # M3 设计定位：文案中以「假设：」开头的行
    brief_txt = _read_text(os.path.join(source_dir, "设计定位.txt"))
    for line in brief_txt.splitlines():
        line = line.strip().lstrip("-·* ").strip()
        if line.startswith("假设："):
            _add(line, "M3 设计定位")

    # M3 材质方案 / 色彩方案
    materials = _read_json(os.path.join(source_dir, "材质方案.json")) or {}
    for item in materials.get("assumptions") or []:
        _add(item, "M3 材质方案")
    palette = _read_json(os.path.join(source_dir, "色彩方案色板.json")) or {}
    for sug in palette.get("room_suggestions") or []:
        note = str((sug or {}).get("note") or "")
        for piece in re.split(r"[；;。]", note):
            if piece.strip().startswith("假设："):
                _add(piece, "M3 色彩方案")

    # M4 布局草案
    layout = _read_json(os.path.join(source_dir, "layout_draft.json")) or {}
    for item in layout.get("assumptions") or []:
        _add(item, "M4 布局草案")

    # M5 预算估算 / 材料清单
    estimate = _read_json(os.path.join(source_dir, "budget_estimate.json")) or {}
    for item in estimate.get("assumptions") or []:
        _add(item, "M5 预算估算")
    material_list = _read_json(os.path.join(source_dir, "material_list.json")) or {}
    for item in material_list.get("assumptions") or []:
        _add(item, "M5 材料清单")

    order = ["M3 设计定位", "M3 材质方案", "M3 色彩方案", "M4 布局草案",
             "M5 预算估算", "M5 材料清单"]
    items = [{"text": text, "sources": sources} for text, sources in found.items()]
    items.sort(key=lambda x: min(order.index(s) if s in order else 99 for s in x["sources"]))
    return items


def render_assumptions_index(assumptions, project_name=None):
    lines = ["# 汇总假设清单（M3–M5，自动去重）", ""]
    if project_name:
        lines.append("项目：%s" % project_name)
        lines.append("")
    lines.append("本清单汇总 M3 概念方案、M4 布局草案、M5 预算与材料清单各产物中的全部假设"
                 "（均以「假设：」前缀），相同内容只保留一条并标注所有来源模块。")
    lines.append("所有依赖这些假设的文字与数字结论，必须由设计师现场复核后再对业主承诺。")
    lines.append("")
    lines.append("共 %d 条（去重后）：" % len(assumptions))
    lines.append("")
    for idx, item in enumerate(assumptions, 1):
        lines.append("%d. %s" % (idx, item["text"]))
        lines.append("   - 来源模块：%s" % "、".join(item["sources"]))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Budget workbook (openpyxl) — numbers copied verbatim from the M5 JSON
# ---------------------------------------------------------------------------

def build_budget_workbook(estimate, material_list, output_path):
    """Export budget_estimate.json + material_list.json to a styled workbook.

    Sheets: 总览 / 分房间分项预算 / 材料清单. All numbers are copied verbatim
    from the rule-engine JSON; this function never recomputes anything.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    group_font = Font(bold=True)
    group_fill = PatternFill("solid", fgColor="D9E1F2")
    total_font = Font(bold=True)
    thin = Side(style="thin", color="B0B0B0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    def _style_header(ws, row, ncols):
        for col in range(1, ncols + 1):
            cell = ws.cell(row=row, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = border
            cell.alignment = Alignment(vertical="center")

    def _write_row(ws, row, values, ncols, font=None, fill=None, wrap_cols=()):
        for col in range(1, ncols + 1):
            cell = ws.cell(row=row, column=col, value=values[col - 1])
            cell.border = border
            if font:
                cell.font = font
            if fill:
                cell.fill = fill
            if col in wrap_cols:
                cell.alignment = wrap
        return row + 1

    def _set_widths(ws, widths):
        for idx, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(idx)].width = width

    def _fmt_range(low, high):
        return "%.0f ~ %.0f" % (low or 0, high or 0)

    wb = Workbook()

    # --- Sheet 1: 总览 ------------------------------------------------------
    ws = wb.active
    ws.title = "总览"
    project = estimate.get("project") or {}
    tier = estimate.get("tier") or {}
    totals = estimate.get("totals") or {}
    comparison = estimate.get("budget_comparison") or {}
    baseline = estimate.get("price_baseline") or {}
    rows = [
        ("预算方案总览（区间参考价，非报价单）", ""),
        ("", ""),
        ("项目名称", project.get("name") or "未命名项目"),
        ("建筑面积(㎡)", project.get("area_m2")),
        ("价格档次", "%s（%s）" % (tier.get("level", ""), tier.get("basis", ""))),
        ("价格基准", "%s（%s）" % (baseline.get("source", ""), baseline.get("reference", ""))),
        ("总价区间下限(元)", totals.get("low")),
        ("总价区间上限(元)", totals.get("high")),
        ("用户预算(元)", comparison.get("user_budget")),
        ("预算比对", comparison.get("conclusion") or "（未提供用户预算，未比对）"),
    ]
    overruns = comparison.get("overrun_items") or []
    if overruns:
        rows.append(("主要超支项", "；".join(
            "%s（上限约 %.0f 元）" % (i.get("label", ""), i.get("subtotal_high", 0))
            for i in overruns)))
    rows.append(("重要提示", "本表数字由规则引擎按价格基准表估算，须按当地市场校准后方可作为报价依据。"))
    for r, (key, value) in enumerate(rows, 1):
        ws.cell(row=r, column=1, value=key).font = Font(bold=bool(key))
        cell = ws.cell(row=r, column=2, value=value)
        cell.alignment = wrap
        if isinstance(value, (int, float)):
            cell.number_format = "#,##0.00"
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    _set_widths(ws, [22, 80])

    # --- Sheet 2: 分房间分项预算 ---------------------------------------------
    ws = wb.create_sheet("分房间分项预算")
    headers = ["房间", "类别", "项目", "工程量", "单位", "工程量来源",
               "单价区间(元)", "单价依据", "小计区间(元)"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"
    row = 2

    def _write_item(ws, row, room_name, item):
        values = [
            room_name,
            item.get("category", ""),
            item.get("item", ""),
            round(item.get("quantity", 0), 2),
            item.get("unit", ""),
            item.get("quantity_basis", ""),
            _fmt_range(item.get("unit_price_low"), item.get("unit_price_high")),
            item.get("unit_price_basis", ""),
            _fmt_range(item.get("subtotal_low"), item.get("subtotal_high")),
        ]
        row = _write_row(ws, row, values, len(headers), wrap_cols=(6, 8))
        ws.cell(row=row - 1, column=4).number_format = "0.00"
        return row

    for room in estimate.get("rooms") or []:
        row = _write_row(ws, row, [
            "%s（面积 %.2f㎡，小计 %s 元）" % (
                room.get("name", ""), room.get("area_m2", 0),
                _fmt_range(room.get("subtotal_low"), room.get("subtotal_high"))),
            "", "", "", "", "", "", "", "",
        ], len(headers), font=group_font, fill=group_fill)
        for item in room.get("items") or []:
            row = _write_item(ws, row, room.get("name", ""), item)

    whole = estimate.get("whole_house_items") or []
    if whole:
        whole_low = sum(i.get("subtotal_low", 0) for i in whole)
        whole_high = sum(i.get("subtotal_high", 0) for i in whole)
        row = _write_row(ws, row, [
            "全屋项目（小计 %s 元）" % _fmt_range(whole_low, whole_high),
            "", "", "", "", "", "", "", "",
        ], len(headers), font=group_font, fill=group_fill)
        for item in whole:
            row = _write_item(ws, row, "全屋项目", item)

    row = _write_row(ws, row, [
        "合计", "", "", "", "", "", "", "",
        _fmt_range(totals.get("low"), totals.get("high")),
    ], len(headers), font=total_font, fill=group_fill)
    _set_widths(ws, [14, 10, 22, 10, 8, 34, 16, 34, 16])

    # --- Sheet 3: 材料清单 ----------------------------------------------------
    ws = wb.create_sheet("材料清单")
    headers = ["材料", "用量", "单位", "价位档", "用量来源", "单价依据"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"
    row = 2
    for item in (material_list or {}).get("items") or []:
        row = _write_row(ws, row, [
            item.get("material", ""),
            round(item.get("quantity", 0), 2),
            item.get("unit", ""),
            item.get("tier", ""),
            item.get("quantity_basis", ""),
            item.get("price_basis", ""),
        ], len(headers), wrap_cols=(5, 6))
        ws.cell(row=row - 1, column=2).number_format = "0.00"
    _set_widths(ws, [26, 10, 8, 10, 36, 36])

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    wb.save(output_path)
    return output_path


# ---------------------------------------------------------------------------
# 交付说明.md
# ---------------------------------------------------------------------------

def render_delivery_readme(manifest, assumptions, estimate, material_list, project_name):
    gate = manifest["gate"]
    generation = manifest["generation"]
    mode_label = "离线演示模式（demo）" if generation["mode"] == "demo" else \
        "真实 AI 模式（provider：%s）" % generation.get("provider", "")

    lines = ["# 交付说明 —— %s" % project_name, ""]
    lines.append("生成时间：%s；生成模式：%s。" % (
        manifest["package"]["created_at"], mode_label))
    lines.append("")
    lines.append("## 这个包是什么")
    lines.append("")
    lines.append("这是设计师 AI 工具箱自动生成的**设计前期提案交付包**：从空间对象建档（M0）、"
                 "需求解析（M1）、约束检查（M2）到概念方案（M3）、布局草案（M4）、预算与材料清单（M5）"
                 "的全部产物，一次性打包并保留每个文件的来源与假设（M6）。")
    lines.append("它是**可审阅、可编辑、可追溯的提案初稿**，不是施工图纸，也不是报价单。")
    lines.append("")
    lines.append("## 目录结构（每部分给谁看）")
    lines.append("")
    lines.append("- `01_业主版/` —— 给业主：概念方案 PPTX 与风格意向板图片。")
    lines.append("- `02_设计师工作版/` —— 给设计师：布局草案 JSON 与摘要、预算 Excel"
                 "（分房间分项预算 + 材料清单，含工程量来源与单价依据）、M3/M4/M5 工作 JSON。")
    lines.append("- `03_事实与假设/` —— 双方复核用：M0/M1/M2 全套事实档案 JSON、"
                 "待确认问题清单、汇总假设清单（assumptions_index.md）。")
    lines.append("- `manifest.json` —— 机器可读交付清单：每个文件的来源模块、生成时间、"
                 "schema 版本、生成模式，以及闸门拦截记录。")
    lines.append("")

    lines.append("## 闸门状态（哪些内容被拦截及原因）")
    lines.append("")
    if gate["allowed"]:
        labels = [GATE_MODULE_LABELS.get(m, m) for m in gate["allowed"]]
        lines.append("已放行：%s。" % "、".join(labels))
    if gate["blocked"]:
        lines.append("")
        lines.append("以下模块被 M2 自动化闸门拦截，**交付包中没有也不会伪造它们的产物**：")
        lines.append("")
        for item in gate["blocked"]:
            lines.append("- **%s**：" % item["label"])
            for reason in item["reasons"]:
                lines.append("  - %s" % reason)
    else:
        lines.append("")
        lines.append("本次没有模块被拦截。")
    for warning in gate.get("warnings") or []:
        lines.append("- 闸门提醒：%s" % warning)
    lines.append("")

    lines.append("## 哪些数字是参考假设、必须校准")
    lines.append("")
    if estimate and estimate.get("status") == "estimate":
        baseline = estimate.get("price_baseline") or {}
        totals = estimate.get("totals") or {}
        lines.append("- 预算总价区间 %.0f ~ %.0f 元为**区间参考价**：单价全部来自价格基准表"
                     "（%s，%s），须按当地市场与当季行情校准后才能作为报价依据。" % (
                         totals.get("low", 0), totals.get("high", 0),
                         baseline.get("source", ""), baseline.get("reference", "")))
        lines.append("- 工程量来自空间事实或透明默认常量，每一项在 Excel/JSON 中都注明了"
                     "「工程量来源」；带默认常量的项必须现场复尺。")
    else:
        lines.append("- 本次未生成预算估算（见上方闸门状态），无预算数字需要校准。")
    lines.append("- 全部推断已集中在 `03_事实与假设/assumptions_index.md`"
                 "（共 %d 条，去重后），每条标注来源模块；凡依赖这些假设的结论，"
                 "设计师复核前不要对业主承诺。" % len(assumptions))
    questions_path = FACTS_DIR + "/unified_questions_to_confirm.json"
    lines.append("- 待确认问题见 `%s`，其中的必答项（required）建议在与业主下次沟通时逐项确认。" % questions_path)
    lines.append("")

    lines.append("## 下一步建议")
    lines.append("")
    actionable_blocked = [b for b in gate["blocked"] if b.get("module") != "construction_docs"]
    if actionable_blocked:
        lines.append("1. 先补齐被拦截模块缺失的事实（见上方拦截原因），再重跑流水线让对应模块放行。")
    else:
        lines.append("1. 设计师审阅 `02_设计师工作版/`，按现场复尺校准工程量与价格基准。")
    lines.append("2. 与业主逐项确认 `03_事实与假设/` 中的待确认问题，更新输入后重新生成。")
    lines.append("3. 用 `01_业主版/` 的 PPTX 做提案汇报；预算 Excel 仅作内部测算底稿，不直接发业主。")
    lines.append("4. 施工级图纸/文档始终不在自动生成范围内，必须由设计师基于原始图纸绘制并签字负责。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _manifest_entry(src_path, rel_dest, audience, module, generation_mode, provider,
                    note=None):
    entry = {
        "path": rel_dest,
        "audience": audience,
        "audience_label": AUDIENCE_LABELS.get(audience, audience),
        "source_module": module,
        "source_module_label": MODULE_LABELS.get(module, module),
        "source_artifact": os.path.abspath(src_path),
        "generated_at": datetime.fromtimestamp(
            os.path.getmtime(src_path)).isoformat(timespec="seconds"),
        "schema_version": _schema_version_of(src_path),
        "generation_mode": _generation_mode_of(src_path, generation_mode),
        "provider": provider,
    }
    if note:
        entry["note"] = note
    return entry


def _schema_version_of(path):
    if not path.endswith(".json"):
        return None
    data = _read_json(path)
    if isinstance(data, dict):
        return data.get("schema_version")
    return None


def _generation_mode_of(path, package_default):
    if not path.endswith(".json"):
        return package_default
    data = _read_json(path)
    if not isinstance(data, dict):
        return package_default
    generation = data.get("generation")
    if isinstance(generation, dict) and generation.get("mode"):
        return generation["mode"]
    if data.get("demo") is True:
        return "demo"
    return package_default


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _read_project_name(source_dir):
    data = _read_json(os.path.join(source_dir, "space_profile.json"))
    if isinstance(data, dict):
        name = (data.get("project") or {}).get("name")
        if name:
            return name
    return None


def _sanitize_name(name):
    name = re.sub(r"[^\w一-鿿-]+", "_", str(name)).strip("_")
    return name or "未命名项目"
