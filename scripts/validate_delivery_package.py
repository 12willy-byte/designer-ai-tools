"""Offline validation for the M6 delivery package module.

Covers:
A. Scan scenario (RoomPlan semantic template, gate fully open): the pipeline
   assembles a complete delivery package — directory structure, manifest
   entries that all exist and carry full source fields, blocked modules
   correctly labelled, assumptions_index.md deduped with M3/M4/M5 sources,
   the budget workbook opens with all sheets/columns and its numbers match
   budget_estimate.json (spot-checked), and 交付说明.md contains the blocked
   notice and calibration warnings.
B. Blocked scenario (design_conditions.sample.json, no geometry facts):
   layout_draft is blocked — the package is still assembled, no layout files
   are fabricated, the manifest records the blocked module with reasons, and
   交付说明.md explains the block. Budget IS allowed here (area + budget
   known) so the workbook must exist.
C. Dedupe unit check: identical assumption texts from different modules merge
   into one entry carrying both sources.

Run: AI_DEMO_MODE=1 python3 scripts/validate_delivery_package.py
"""
import json
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

os.environ["AI_DEMO_MODE"] = "1"


def _fail(message):
    raise SystemExit("FAIL: " + message)


def _scan_conditions(path, budget=280000):
    data = {
        "project": {"name": "扫描样例两室一厅", "house_type": "两室一厅", "area_m2": 68,
                    "design_type": "整屋自动化方案"},
        "family": {"residents": "3人(夫妻+1孩)", "work_from_home": "偶尔", "storage_need": "较高",
                   "cooking_frequency": "高频中餐"},
        "style": {"primary_style": "现代简约", "color_tone": "暖白、原木色、低饱和蓝灰",
                  "keywords": "通透 温润 收纳"},
        "rooms": [
            {"name": "客厅", "requirements": {"功能": "会客、观影、亲子活动"}},
            {"name": "主卧", "requirements": {"功能": "睡眠、衣物收纳", "备注": "需要整墙衣柜"}},
            {"name": "次卧", "requirements": {"功能": "儿童房,兼顾书房"}},
            {"name": "厨房", "requirements": {"功能": "高频中餐,需要大单槽和洗碗机位"}},
            {"name": "卫生间", "requirements": {"功能": "干湿分离"}},
        ],
        "special_requirements": {"承重墙": "外墙及结构墙不可拆改，需保留",
                                 "上下水": "厨房与卫生间湿区位置不可移动"},
    }
    if budget is not None:
        data["budget"] = {"total_budget": budget}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_range(text):
    nums = re.findall(r"-?\d+(?:\.\d+)?", str(text))
    if len(nums) != 2:
        _fail("cannot parse range %r" % text)
    return float(nums[0]), float(nums[1])


def _check_structure(package_dir):
    for sub in ("01_业主版", "02_设计师工作版", "03_事实与假设"):
        if not os.path.isdir(os.path.join(package_dir, sub)):
            _fail("delivery package missing directory %s" % sub)
    for name in ("manifest.json", "交付说明.md"):
        if not os.path.exists(os.path.join(package_dir, name)):
            _fail("delivery package missing %s" % name)


def _check_manifest(package_dir, expect_workbook=True):
    manifest = _read_json(os.path.join(package_dir, "manifest.json"))
    if manifest.get("schema_version") != "delivery_manifest.v1":
        _fail("manifest schema_version mismatch")
    generation = manifest.get("generation") or {}
    if generation.get("mode") != "demo" or not generation.get("provider"):
        _fail("manifest generation mode/provider wrong: %s" % generation)

    files = manifest.get("files") or []
    if not files:
        _fail("manifest has no files")
    owner_files = [f for f in files if f["audience"] == "owner"]
    if not any(f["path"].endswith("概念方案.pptx") for f in owner_files):
        _fail("owner section must include the concept PPTX")
    if not any(f["path"].endswith(".png") for f in owner_files):
        _fail("owner section must include mood board PNG(s)")
    if expect_workbook and not any(f["path"].endswith("预算方案.xlsx") for f in files):
        _fail("designer section must include the budget workbook")

    for entry in files:
        dest = os.path.join(package_dir, entry["path"])
        if not os.path.exists(dest):
            _fail("manifest file missing on disk: %s" % entry["path"])
        for field in ("source_module", "source_module_label", "source_artifact",
                      "generated_at", "generation_mode", "provider", "audience"):
            if entry.get(field) in (None, ""):
                _fail("manifest entry %s missing field %s" % (entry["path"], field))
        if entry["path"].endswith(".json") and entry["path"] != "manifest.json":
            if "schema_version" not in entry:
                _fail("JSON entry %s should carry a schema_version field" % entry["path"])
            if entry["path"].split("/")[-1] in (
                    "space_profile.json", "needs_profile.json", "automation_gate.json",
                    "budget_estimate.json", "material_list.json", "layout_draft.json"):
                if not entry.get("schema_version"):
                    _fail("fact archive %s must carry a schema_version" % entry["path"])

    # construction_docs 永远被拦截，且必须带原因
    blocked = {b["module"]: b for b in (manifest.get("gate") or {}).get("blocked") or []}
    if "construction_docs" not in blocked:
        _fail("manifest should record construction_docs as blocked")
    if not blocked["construction_docs"].get("reasons"):
        _fail("blocked entry must carry reasons")
    for module, entry in blocked.items():
        if entry.get("files_included"):
            _fail("blocked module %s must not include fabricated files" % module)
    return manifest, blocked


def _check_workbook(package_dir, source_dir):
    from openpyxl import load_workbook

    xlsx = os.path.join(package_dir, "02_设计师工作版", "预算方案.xlsx")
    if not os.path.exists(xlsx):
        _fail("budget workbook missing")
    wb = load_workbook(xlsx)
    for sheet in ("总览", "分房间分项预算", "材料清单"):
        if sheet not in wb.sheetnames:
            _fail("workbook missing sheet %s (has %s)" % (sheet, wb.sheetnames))

    estimate = _read_json(os.path.join(source_dir, "budget_estimate.json"))
    material_list = _read_json(os.path.join(source_dir, "material_list.json"))

    # 总览：总价区间与 JSON 一致
    overview = wb["总览"]
    kv = {}
    for row in overview.iter_rows(values_only=True):
        if row and row[0]:
            kv[str(row[0])] = row[1] if len(row) > 1 else None
    totals = estimate["totals"]
    if abs(float(kv["总价区间下限(元)"]) - totals["low"]) > 0.51:
        _fail("overview total low %.2f != json %.2f" % (kv["总价区间下限(元)"], totals["low"]))
    if abs(float(kv["总价区间上限(元)"]) - totals["high"]) > 0.51:
        _fail("overview total high %.2f != json %.2f" % (kv["总价区间上限(元)"], totals["high"]))
    if abs(float(kv["用户预算(元)"]) - estimate["budget_comparison"]["user_budget"]) > 0.51:
        _fail("overview user budget mismatch")

    # 分房间分项预算：列头齐全 + 逐项数字与 JSON 一致
    sheet = wb["分房间分项预算"]
    header = [c.value for c in sheet[1]]
    expected_cols = ["房间", "类别", "项目", "工程量", "单位", "工程量来源",
                     "单价区间(元)", "单价依据", "小计区间(元)"]
    if header != expected_cols:
        _fail("budget sheet header mismatch: %s" % header)

    json_items = {}
    for room in estimate.get("rooms") or []:
        for item in room.get("items") or []:
            json_items[(room["name"], item["item"])] = item
    for item in estimate.get("whole_house_items") or []:
        json_items[("全屋项目", item["item"])] = item

    excel_items = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if not row or not row[2]:
            continue  # 分组标题行
        excel_items[(row[0], row[2])] = row
    if len(excel_items) != len(json_items):
        _fail("workbook item count %d != json item count %d" % (
            len(excel_items), len(json_items)))
    for key, item in json_items.items():
        row = excel_items.get(key)
        if row is None:
            _fail("workbook missing item %s" % (key,))
        if abs(float(row[3]) - item["quantity"]) > 0.01:
            _fail("%s quantity %.2f != json %.2f" % (key, row[3], item["quantity"]))
        low, high = _parse_range(row[6])
        if abs(low - item["unit_price_low"]) > 0.51 or abs(high - item["unit_price_high"]) > 0.51:
            _fail("%s unit price range %s != json %.2f~%.2f" % (
                key, row[6], item["unit_price_low"], item["unit_price_high"]))
        low, high = _parse_range(row[8])
        if abs(low - item["subtotal_low"]) > 0.51 or abs(high - item["subtotal_high"]) > 0.51:
            _fail("%s subtotal range %s != json %.2f~%.2f" % (
                key, row[8], item["subtotal_low"], item["subtotal_high"]))
        if not row[5] or not row[7]:
            _fail("%s missing 工程量来源/单价依据" % (key,))

    # 材料清单：列头齐全 + 用量与 JSON 一致
    sheet = wb["材料清单"]
    header = [c.value for c in sheet[1]]
    expected_cols = ["材料", "用量", "单位", "价位档", "用量来源", "单价依据"]
    if header != expected_cols:
        _fail("material sheet header mismatch: %s" % header)
    json_materials = {i["material"]: i for i in material_list.get("items") or []}
    excel_materials = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        if row and row[0]:
            excel_materials[row[0]] = row
    if len(excel_materials) != len(json_materials):
        _fail("material count %d != json %d" % (len(excel_materials), len(json_materials)))
    for name, item in json_materials.items():
        row = excel_materials.get(name)
        if row is None:
            _fail("workbook missing material %s" % name)
        if abs(float(row[1]) - item["quantity"]) > 0.01:
            _fail("material %s quantity %.2f != json %.2f" % (name, row[1], item["quantity"]))
        if row[3] != item["tier"] or not row[4] or not row[5]:
            _fail("material %s tier/basis mismatch" % name)
    return {"budget_items": len(excel_items), "materials": len(excel_materials)}


def _check_assumptions_index(package_dir, source_dir, expect_modules):
    path = os.path.join(package_dir, "03_事实与假设", "assumptions_index.md")
    if not os.path.exists(path):
        _fail("assumptions_index.md missing")
    text = _read_text(path)

    # 汇总了 M3/M4/M5 的假设来源
    for label in expect_modules:
        if label not in text:
            _fail("assumptions_index should cite source %s" % label)

    # 去重：正文里每条「假设：」文本只出现一次（来源标注行不算）
    seen = set()
    count = 0
    for line in text.splitlines():
        m = re.match(r"\d+\.\s+(假设：.+)$", line.strip())
        if not m:
            continue
        count += 1
        if m.group(1) in seen:
            _fail("duplicated assumption in index: %s" % m.group(1))
        seen.add(m.group(1))
    if count == 0:
        _fail("assumptions_index has no deduped entries")

    # 汇总条数 <= 各产物假设条数之和（去重生效，且不遗漏）
    raw_total = 0
    for name in ("材质方案.json", "layout_draft.json", "budget_estimate.json",
                 "material_list.json"):
        data = _read_json(os.path.join(source_dir, name)) if os.path.exists(
            os.path.join(source_dir, name)) else {}
        raw_total += len((data or {}).get("assumptions") or [])
    if count > raw_total:
        _fail("index has %d entries but sources only have %d raw assumptions" % (
            count, raw_total))
    m = re.search(r"共\s*(\d+)\s*条", text)
    if not m or int(m.group(1)) != count:
        _fail("index header count mismatch: header=%s, actual=%d" % (
            m.group(1) if m else None, count))
    return {"deduped_assumptions": count, "raw_assumptions": raw_total}


def _check_readme(package_dir, expect_blocked_labels):
    text = _read_text(os.path.join(package_dir, "交付说明.md"))
    for needle in ("这个包是什么", "目录结构", "闸门状态", "校准", "下一步建议"):
        if needle not in text:
            _fail("交付说明 missing section %s" % needle)
    for label in expect_blocked_labels:
        if label not in text:
            _fail("交付说明 should mention blocked %s" % label)
    if "不会伪造" not in text and "不伪造" not in text:
        _fail("交付说明 should state blocked outputs are not fabricated")
    if "assumptions_index.md" not in text:
        _fail("交付说明 should point to the assumptions index")


def scenario_scan(tmp):
    from core.scan_importer import summarize_scan_file
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    case_dir = os.path.join(tmp, "scan_case")
    os.makedirs(case_dir, exist_ok=True)
    conditions_path = os.path.join(case_dir, "design_conditions.json")
    _scan_conditions(conditions_path)
    scan_path = os.path.join(case_dir, "roomplan_scan.json")
    shutil.copy2(os.path.join(ROOT, "templates", "roomplan_scan.template.json"), scan_path)
    scan_summary = summarize_scan_file(scan_path)

    result = run_mvp_concept_package(conditions_path, scan_summary=scan_summary)
    delivery = result.get("delivery")
    if not delivery or not os.path.isdir(delivery["package_dir"]):
        _fail("pipeline did not return a delivery package")
    package_dir = delivery["package_dir"]
    source_dir = result["output_dir"]

    _check_structure(package_dir)
    manifest, blocked = _check_manifest(package_dir)
    if "layout_draft" in blocked or "budget_estimate" in blocked:
        _fail("scan scenario should allow layout and budget")
    workbook_stats = _check_workbook(package_dir, source_dir)
    assumptions_stats = _check_assumptions_index(
        package_dir, source_dir, ["M3 材质方案", "M4 布局草案", "M5 预算估算"])
    _check_readme(package_dir, ["施工级图纸/文档"])

    # 业主版必含 PPTX + 意向板
    owner_dir = os.path.join(package_dir, "01_业主版")
    if not os.path.exists(os.path.join(owner_dir, "概念方案.pptx")):
        _fail("owner section missing PPTX")
    if not os.path.exists(os.path.join(owner_dir, "风格意向板.png")):
        _fail("owner section missing mood board PNG")
    return {
        "package_dir": os.path.basename(package_dir),
        "files": len(manifest["files"]),
        "blocked": sorted(blocked.keys()),
        "generation_mode": manifest["generation"]["mode"],
        **workbook_stats,
        **assumptions_stats,
    }


def scenario_blocked(tmp):
    from modules.m2_concept_design.mvp_pipeline import run_mvp_concept_package

    case_dir = os.path.join(tmp, "blocked_case")
    os.makedirs(case_dir, exist_ok=True)
    conditions_path = os.path.join(case_dir, "design_conditions.json")
    shutil.copy2(os.path.join(ROOT, "templates", "design_conditions.sample.json"),
                 conditions_path)

    result = run_mvp_concept_package(conditions_path)
    if "layout_draft" in result.get("allowed_modules", []):
        _fail("sample conditions should keep layout_draft blocked")
    delivery = result.get("delivery")
    if not delivery or not os.path.isdir(delivery["package_dir"]):
        _fail("blocked scenario should still assemble a delivery package")
    package_dir = delivery["package_dir"]

    _check_structure(package_dir)
    manifest, blocked = _check_manifest(package_dir)
    if "layout_draft" not in blocked:
        _fail("manifest should record layout_draft as blocked")
    if not blocked["layout_draft"].get("reasons"):
        _fail("blocked layout entry must carry reasons")

    # 拦截项不伪造：包内不允许出现布局草案文件
    for root, _dirs, names in os.walk(package_dir):
        for name in names:
            if name in ("layout_draft.json", "layout_draft_summary.md"):
                _fail("blocked layout must not be fabricated in the package: %s" % name)
    # 预算在该场景放行（有面积+总预算）→ Excel 必须存在
    if not os.path.exists(os.path.join(package_dir, "02_设计师工作版", "预算方案.xlsx")):
        _fail("budget is allowed in the sample scenario; workbook should exist")
    _check_workbook(package_dir, result["output_dir"])
    _check_readme(package_dir, ["布局草案"])
    return {"blocked": sorted(blocked.keys()),
            "layout_blocked_reasons": len(blocked["layout_draft"]["reasons"])}


def scenario_dedupe_unit(tmp):
    from core.delivery_package import collect_assumptions

    source_dir = os.path.join(tmp, "dedupe_case")
    os.makedirs(source_dir, exist_ok=True)
    with open(os.path.join(source_dir, "材质方案.json"), "w", encoding="utf-8") as f:
        json.dump({"assumptions": ["假设：孩子年龄按 3-6 岁推断", "假设：仅材质方案有"]}, f,
                  ensure_ascii=False)
    with open(os.path.join(source_dir, "budget_estimate.json"), "w", encoding="utf-8") as f:
        json.dump({"assumptions": ["假设：孩子年龄按 3-6 岁推断", "假设：仅预算有"]}, f,
                  ensure_ascii=False)
    items = collect_assumptions(source_dir)
    texts = [i["text"] for i in items]
    if len(texts) != len(set(texts)):
        _fail("collect_assumptions must dedupe identical texts")
    merged = next((i for i in items if i["text"] == "假设：孩子年龄按 3-6 岁推断"), None)
    if merged is None:
        _fail("shared assumption missing")
    if set(merged["sources"]) != {"M3 材质方案", "M5 预算估算"}:
        _fail("merged assumption should cite both sources: %s" % merged["sources"])
    if len(items) != 3:
        _fail("expected 3 deduped assumptions, got %d" % len(items))
    return {"merged_sources": merged["sources"], "total": len(items)}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        scan_result = scenario_scan(tmp)
        blocked_result = scenario_blocked(tmp)
        dedupe_result = scenario_dedupe_unit(tmp)

    print(json.dumps({
        "ok": True,
        "scan_scenario": scan_result,
        "blocked_scenario": blocked_result,
        "dedupe_scenario": dedupe_result,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
