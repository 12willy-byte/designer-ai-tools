# templates/ —— 输入模板与样例数据

本目录提供流水线的四类输入模板。**统一单位：长度 = 毫米（mm），面积 = 平方米（㎡），预算 = 人民币元。**
所有 JSON 中以 `_` 开头的键（如 `_comment`、`_说明`）都是注释，解析器会忽略，可保留。

| 文件 | 用途 | 喂给哪个环节 |
|------|------|--------------|
| `sample_roomplan.json` | 苹果 RoomPlan **原生导出格式**的两室一厅样例（surfaces/transform/rooms） | 旧版流水线 `python3 main.py sample`（`Scene3D.from_roomplan`） |
| `roomplan_scan.template.json` | LiDAR/RoomPlan **语义扫描**输入模板（房间/门窗列表） | M0 空间建档：`core.scan_importer.summarize_scan_file()` |
| `manual_space_data.template.json` | 手动量房数据模板（含中文填写说明） | 直接作为 design_conditions 喂给 MVP 概念提案流水线 |
| `design_conditions.sample.json` | 完整设计条件样例（可独立复用） | MVP 概念提案流水线 |

## 1. sample_roomplan.json（RoomPlan 原生格式样例）

- 供 `core/scene3d.py` 的 `Scene3D.from_roomplan()` 加载，结构为苹果 RoomPlan 原始导出：
  顶层 `surfaces`（每个面含 `identifier`、`category`（wall/door/window）、列主序 4×4 `transform`、
  `dimensions {x, y, z}`，门窗另有 `parentIdentifier` 指向所在墙）+ 顶层 `rooms`
  （`identifier`、`displayName`、`surfaces` 墙 id 列表）。
- 样例为 8.6m × 7.6m 两室一厅：客厅 21.76㎡、主卧 18.48㎡、次卧 17.64㎡、厨房/卫生间各 3.74㎡，
  5 门 5 窗，层高 2800mm。
- **注意**：该文件是几何格式，不含语义房间尺寸，**不适合**直接喂给 scan_importer；扫描语义输入请用
  `roomplan_scan.template.json`。
- 用法：`python3 main.py sample`（旧版流水线，见下方「旧版流水线状态」）。

## 2. roomplan_scan.template.json（语义扫描输入模板）

- 供 `core/scan_importer.py` 的 `summarize_scan_file()` 解析（支持 `.json` / `.roomplan`）。
- 顶层键：`rooms`（或 `spaces`）、`openings`（或 `doors_windows`）、`objects`（或 `furniture`，可选）、
  `source_type`、`confidence`、`bounds_mm`。
- 房间字段：`name`（必填）、`width_mm`、`length_mm`、`area_m2`（可不填，自动 = 宽×长）、
  `ceiling_height_mm`、`orientation`、`adjacent_to`、`confidence`。
- 开口字段：`type`（door/window/opening）、`room`、`width_mm`、`height_mm`、`orientation`、`connects_to`。
- 解析示例：

  ```python
  from core.scan_importer import summarize_scan_file
  summary = summarize_scan_file("templates/roomplan_scan.template.json")
  # summary["rooms"] -> 5 个房间；summary["openings"] -> 5 门 5 窗
  ```

- 接入 M0：`run_mvp_concept_package(conditions_path, scan_summary=summary)`。

## 3. manual_space_data.template.json（手动量房模板）

- 没有 CAD 也没有扫描时，用卷尺量房后照此填写；文件内每个字段都有中文 `_注释`。
- 结构对齐 `core/space_profile.py` 的 conditions 输入：`project` + `space_data.rooms`
  （`name`/`width_mm`/`length_mm`/`ceiling_height_mm`/`orientation`/`adjacent_to`/`requirements`）
  + `family` + `style` + `budget` + `special_requirements`。
- `special_requirements` 中键名含「承重/梁/柱/结构」的条目会被识别为结构约束，含「水/电/燃气/烟道/管井」
  的条目会被识别为机电约束——这两项决定自动化闸门是否放行布局草案；未确认时系统会**安全拦截**布局，
  而不是伪造方案。

## 4. design_conditions.sample.json（设计条件样例）

- 一份完整、可直接运行的 design_conditions（参考 `scripts/validate_mvp.py` 的内置样例扩展为 5 房间）。
- 未包含结构/机电确认，因此自动化闸门会拦截布局草案（`布局方案.json` 中带原因），
  概念提案包（设计定位/色板/材质/意向板/PPT）正常生成。

## 喂给流水线的命令

```bash
# MVP 概念提案流水线（M0 空间建档 -> M1 需求认知 -> M2 闸门 -> 概念 PPT）
AI_DEMO_MODE=1 python3 -m modules.m2_concept_design.mvp_pipeline \
    templates/design_conditions.sample.json 输出.pptx
# 第三个可选参数可接 CAD 图纸：... 输出.pptx 原始平面图.dxf
# 产物写在输入文件同级的 concept_output/ 目录（已被 .gitignore 忽略）

# 旧版 3D 流水线（Scene3D -> 自动布置 -> 预算 -> glb/html/DXF/施工图）
python3 main.py sample
```

## 旧版流水线状态说明

`main.py`（Scene3D/渲染/施工图那套）为旧版入口。当前 `python3 main.py sample` 可完整跑通：
加载本目录 `sample_roomplan.json`（16 墙 / 5 房间 / 5 门 / 5 窗），自动布置家具、生成预算、
`scene.glb`、`3d_preview.html`、`floor_plan.dxf` 和 7 张施工图，输出到 `output/sample/`。
但 `renders/` 目录为空——`core/cloud_renderer.py` 依赖外部云渲染服务，未配置时静默跳过，
属已知遗留行为，不影响其余产物。新需求请优先使用 MVP 概念提案流水线（`mvp_pipeline`）。
