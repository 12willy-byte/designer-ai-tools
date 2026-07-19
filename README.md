# 设计师 AI 辅助自动化工具

> AI 辅助室内设计师提效 —— 从空间对象建档到概念提案包的自动化流水线

## 核心理念

项目目标是逐步走向全自动化设计流程，但自动化必须建立在可验证的空间对象认知上。
工具负责空间建档、需求解析、方案初稿和交付打包，设计师负责审核、判断和最终交付责任。

## 项目结构

```text
├── core/                          # 核心引擎
│   ├── data_model.py              # 统一数据模型
│   ├── space_profile.py           # 空间对象档案 / 自动化流程基础
│   ├── needs_profile.py           # 业主需求画像
│   ├── automation_gate.py         # 约束判断 / 自动化闸门
│   ├── layout_draft.py            # M4 布局草案（规则引擎 + AI 文字增强）
│   ├── ai_client.py               # 统一 LLM 客户端
│   ├── cad_reader.py              # DXF 图纸读取
│   ├── survey_parser.py           # Excel 问卷 -> 设计条件
│   └── template_generator.py      # 生成问卷 Excel 模板
│
├── modules/
│   ├── config.py                  # API 配置（环境变量）
│   ├── generate_template.py       # [旧] 问卷模板生成
│   ├── parse_survey.py            # [旧] 问卷解析
│   └── m2_concept_design/         # 概念方案（色板/材质/PPT）
│
├── templates/                     # 输入模板与样例数据（详见 templates/README.md）
│   ├── sample_roomplan.json       # RoomPlan 原生格式样例（main.py sample 用）
│   ├── roomplan_scan.template.json # LiDAR/语义扫描输入模板（scan_importer 用）
│   ├── manual_space_data.template.json # 手动量房数据模板（含中文填写说明）
│   └── design_conditions.sample.json   # 设计条件样例（mvp_pipeline 用）
│
├── .env.example                   # 环境变量模板
├── .gitignore
└── README.md
```

## 快速开始

### 1. 配置 API 密钥

```bash
cp .env.example .env
# 编辑 .env 填入你的 DeepSeek API Key
```

### 2. 生成需求问卷

```python
from core.template_generator import generate_template
generate_template("问卷.xlsx")
```

### 3. 解析客户问卷

```python
from core.survey_parser import parse_survey, save_conditions
conditions = parse_survey("客户填写的问卷.xlsx")
save_conditions(conditions, "设计条件.json")
```

### 4. 读取 CAD 图纸

```python
from core.cad_reader import read_dxf_floor_plan
plan = read_dxf_floor_plan("原始结构图.dxf")
print(f"发现 {plan['total_lines']} 条可识别线段")
```

### 5. 跑通概念提案流水线（离线演示）

```bash
AI_DEMO_MODE=1 python3 -m modules.m2_concept_design.mvp_pipeline \
    templates/design_conditions.sample.json 概念方案.pptx
```

输入模板（手动量房 / LiDAR 扫描 / RoomPlan 样例）见 `templates/README.md`。

## AI 功能

| 功能 | 模块 | 状态 |
|------|------|:----:|
| Excel 问卷生成 | core/template_generator.py | ✅ |
| 问卷解析 → JSON | core/survey_parser.py | ✅ |
| 空间对象建档 | core/space_profile.py | ✅ |
| LiDAR/扫描摘要 | core/scan_importer.py | ✅ |
| 业主需求认知 | core/needs_profile.py | ✅ |
| 约束判断 / 自动化闸门 | core/automation_gate.py | ✅ |
| CAD/DXF 读取并接入空间画像 | core/cad_reader.py | ✅ |
| 设计定位文案 | modules/m2_concept_design/step1 | ✅ |
| 色彩方案建议 | modules/m2_concept_design/step2 | ✅ |
| 材质方案 | modules/m2_concept_design/step3 | ✅ |
| 风格意向板 | modules/m2_concept_design/step4 | ✅ |
| 布局建议（旧，AI 直出） | modules/m2_concept_design/step5 | ✅ |
| 布局草案（M4，闸门放行后生成） | core/layout_draft.py + step5 | ✅ |
| 概念PPT打包 | modules/m2_concept_design/step7 | ✅ |

## 环境变量

| 变量名 | 说明 |
|--------|------|
| AI_PROVIDER | 模型供应商：deepseek（默认，推荐）/ openai / moonshot |
| AI_MODEL / AI_API_KEY / AI_BASE_URL | 通用覆盖项，优先级高于各厂商专有变量 |
| DEEPSEEK_API_KEY | DeepSeek API 密钥 |
| DEEPSEEK_BASE_URL | API 地址（默认官方） |
| OPENAI_API_KEY / MOONSHOT_API_KEY | 其他厂商密钥（可选，用于模型对比） |
| DASHSCOPE_API_KEY | 阿里云 DashScope 密钥（可选） |

### 模型选型

经真实模式同场对比（见 `outputs/model-compare/quality-report.md`），**默认推荐 `deepseek-chat`**：中文设计文案贴合度与推理模型 `deepseek-reasoner` 同档，但速度快约 2 倍、成本更低、输出结构更稳定。可用 `scripts/compare_models.py` 自行复测：

```bash
python3 scripts/compare_models.py --providers deepseek,openai
```

## 自动化模块顺序

1. M0 空间对象认知：导入 LiDAR/扫描、CAD 或手动房间数据，输出 `space_profile.json`、`cad_plan.json`、`scan_summary.json`、`space_observations.json`、`questions_to_confirm.json`。
2. M1 业主需求认知：解析家庭、生活方式、风格、预算和各空间需求，输出 `needs_profile.json`、`needs_observations.json`、`needs_questions_to_confirm.json`。
3. M2 约束判断：基于 M0/M1 输出 `automation_gate.json`、`constraint_report.json`、`unified_questions_to_confirm.json`，判断能否进入概念、布局、预算等后续自动化。
4. M4 布局草案：闸门放行 `layout_draft` 后，由 `core/layout_draft.py` 基于空间事实（房间尺寸、门窗位置与宽度、相邻关系）和 M1 需求档案生成逐房间的布局草案——功能分区、家具布置（名称+尺寸+靠墙关系）、动线与现场确认点位，输出 `layout_draft.json` 和 `layout_draft_summary.md`，PPT 布局页同步展示草案或拦截原因。几何决策全部由规则引擎完成（家具尺寸按房间净尺寸校验、高柜避让门扇开启范围、窗前固定家具限高），真实模式下 AI 只做文字增强，不能新增房间或修改尺寸；推断统一进 `assumptions` 并以「假设：」前缀。
5. M3+ 概念方案、材料预算和交付打包。

当前流水线会先经过 M2。如果空间和需求足够，会继续生成概念提案；如果资料不足以自动布局，会生成带原因的 `布局方案.json` 拦截结果，而不是伪造布局草案。

CAD/DXF 可通过 `run_mvp_concept_package(..., cad_dxf_path="原始平面图.dxf")` 接入。系统会读取墙线、门窗、文字标注和疑似房间闭环，并把结果写入 M0 空间画像；但承重、上下水、烟道和电气约束仍需要原始图纸或人工确认。
